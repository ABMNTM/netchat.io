from socket import socket, AF_INET, SOCK_STREAM
from threading import Thread, Semaphore
import enum
import struct
import os
import re

BUFFER_SIZE = 128 * 1024  # 128 KB


class MessageType(enum.Enum):
    TEXT = "text"
    FILE = "file"


def start_proc(name):
    t = input(f"start {name}? (y/n) ")
    if t.lower() == "y":
        return True
    if t.lower() == "n":
        return False
    print("just n or y ...")
    return start_proc(name)


class NetChatProtocol:

    def __init__(self):
        self.server = socket(AF_INET, SOCK_STREAM)
        self.client = socket(AF_INET, SOCK_STREAM)
        self.current_connection = None  # for server operations

    def init_server(self, host, port):
        self.server.bind((host, port))
        self.server.listen(5)

    def set_connection(self, connection):
        print(f"connected to {connection}")
        self.current_connection = connection

    def disconnect(self):
        if self.current_connection:
            self.current_connection.close()

    def send_message(self, message: str, connection=True):
        encoded_message = message.encode()
        message_len = len(encoded_message)
        try:
            header = struct.pack("!I", message_len)
            if connection:
                self.current_connection.sendall(header + encoded_message)  # 4 + len_msg
            else:
                self.client.sendall(header + encoded_message)  # 4 + len_msg
            return True
        except Exception as e:
            print("error in sending message :", e.args)
            return False

    def receive_message(self, connection=True) -> bytes:
        header = self._receive_exactly(4, connection)  # receive message length as header
        if not header:
            raise ConnectionResetError("Connection reset by peer")
        message_len = struct.unpack("!I", header)[0]
        message = self._receive_exactly(message_len, connection)
        if not message:
            raise ConnectionResetError("Connection reset by peer")
        return message

    def _receive_exactly(self, size, connection=True):
        data = b""
        while len(data) < size:
            if connection:
                tmp_data = self.current_connection.recv(size - len(data))
            else:
                tmp_data = self.client.recv(size - len(data))
            if not tmp_data:
                raise ConnectionResetError("connection closed")
            data += tmp_data
        return data

    def send_file(self, file_path):
        if not os.path.exists(file_path):
            raise FileNotFoundError
        if os.path.isdir(file_path):
            raise IsADirectoryError

        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        # opening session with format
        # >>> "file:<file_name>:<file_size>"
        self.send_message(f"file:{file_name}:{file_size}", connection=False)

        if self.receive_message(connection=False) == b"ready":
            with (open(file_path, "rb") as file):
                bytes_sent = 0  # no data sent
                while bytes_sent < file_size:
                    buffer = file.read(min(BUFFER_SIZE, file_size - bytes_sent))
                    self.client.sendall(buffer)
                    bytes_sent += len(buffer)
                return True
        return False

    def receive_file(self, file_name, file_size):
        # message is sending to client that requests to send a file
        self.send_message("ready", connection=True)

        with open(file_name, "wb", buffering=BUFFER_SIZE) as file:

            bytes_received = 0
            while bytes_received < file_size:
                buffer = self._receive_exactly(min(BUFFER_SIZE, file_size - bytes_received), connection=True)
                bytes_received += len(buffer)
                file.write(buffer)
            file.flush()
        return file_name


class ChatRoom:
    def __init__(self, src_host: str, src_port: int, dest_host: str, dest_port: int):
        self.protocol = NetChatProtocol()
        self.src_host = src_host
        self.src_port = src_port
        self.dest_host = dest_host
        self.dest_port = dest_port
        self.send_thread = Thread(target=self.send_target)
        self.receive_thread = Thread(target=self.receive_target)

        self.__semaphore = Semaphore()
        self.__running = False

    def show_message(self, message, me=True):
        border = '*' if me else '%'
        host = self.src_host if me else self.dest_host
        port = self.src_port if me else self.dest_port
        print()
        print(border * (len(message) + 22))
        print(f"[{host}:{port}] {message}")
        print(border * (len(message) + 22))
        print()

    def receive_target(self):
        self.protocol.init_server(self.src_host, self.src_port)

        try:
            while self.__running:
                c_socket, addr = self.protocol.server.accept()
                self.protocol.set_connection(c_socket)
                try:
                    while self.__running:
                        try:
                            message = self.protocol.receive_message(connection=True)
                            if not message:
                                break
                            message = message.decode("utf-8")
                            if rematch := re.match(r"file:(.*):(\d*)", message):
                                filename = rematch.group(1)
                                filesize = int(rematch.group(2))
                                self.protocol.receive_file(filename, filesize)
                                self.show_message("file {} received successfully!".format(filename), me=False)
                            else:
                                with self.__semaphore:
                                    self.show_message(message, me=False)
                        except (ConnectionResetError, BrokenPipeError):
                            print("Client disconnected")
                            break
                        except KeyboardInterrupt:
                            self.protocol.disconnect()
                            self.protocol.set_connection(None)
                        except UnicodeDecodeError:
                            print("error: unknown message received.")
                        except Exception as e:
                            print(f"Error receiving message: {e}")
                            break
                finally:
                    self.protocol.disconnect()
                    self.protocol.set_connection(None)
        except Exception as e:
            print(f"server layer error in receiving message from {self.src_port} :", e.args)
        finally:
            self.protocol.server.close()

    def send_target(self):
        if start_proc("client process"):
            try:
                self.protocol.client.connect((self.dest_host, self.dest_port))
                while self.__running:
                    try:
                        message = input("input your message (or 'quit' to exit): \n")
                        if message.lower() == "quit":
                            self.__running = False
                            break

                        if os.path.isfile(message):
                            self.protocol.send_file(message)
                            self.show_message("file {} sent successfully!".format(message), me=True)
                        else:
                            self.protocol.send_message(message, connection=False)
                        self.show_message(message, me=True)
                    except KeyboardInterrupt:
                        print("Bye ...")
                        self.__running = False
                        break
            except ConnectionRefusedError:
                print("Connection refused!")
            except BrokenPipeError:
                print("Broken pipe!")

            except FileNotFoundError:
                print("file not found!")
            except IsADirectoryError:
                print("file not found! input is a directory")
            except Exception as e:
                print(f"error in connecting to {self.src_host}:{self.src_port} :", e.args)
            finally:
                self.protocol.client.close()
        else:
            self.__running = False
            print("Abort!")

    def run(self):
        self.__running = True

        self.send_thread.start()
        self.receive_thread.start()

        self.send_thread.join()
        self.receive_thread.join()


if __name__ == '__main__':
    import sys
    chat = ChatRoom(sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
    chat.run()
