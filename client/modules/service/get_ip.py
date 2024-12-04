import socket


def get_pub_ip():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("255.255.255.0", 80))
            local_ip = s.getsockname()[0]
        return local_ip

print(get_pub_ip())