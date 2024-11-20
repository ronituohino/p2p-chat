import shelve
from concurrent import futures
import socket
import uuid

import gevent
import gevent.pywsgi
import gevent.queue
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher


dispatcher = RPCDispatcher()
groups =  shelve.open(f"groups.db", writeback=True) 
port=50001

class Response:
    def __init__(self, success: bool, message: str, data=None):
        self.success = success
        self.message = message
        self.data = data

    def __repr__(self):
        return f"Response(success={self.success}, message='{self.message}', data={self.data})"

    def to_dict(self):
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }


def serve(port):
    transport=WsgiServerTransport(queue_class=gevent.queue.Queue)
    wsgi_server = gevent.pywsgi.WSGIServer(('127.0.0.1', port), transport.handle)
    gevent.spawn(wsgi_server.serve_forever)
    rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
    rpc_server.serve_forever()


@dispatcher.public
def create_group(leader_ip, group_name):
    """Create a new chat."""
    group_id = str(uuid.uuid4())

    if group_id not in groups:
        groups[group_id] = {
            "leader_ip": leader_ip,
            "group_id": group_id,
            "group_name": group_name
        }
        return Response(success=True, message="Chat creation successful", data={"group_id": group_id})
    return Response(success=False, message="Chat creation failed.")


@dispatcher.public
def get_groups():
    """Get all possible chats to join."""
    group_list = []
    for group in groups.values():
        group_list.append(group)
    return group_list


@dispatcher.public
def update_group_leader(group_id, new_leader_ip):
	"""Updates a leader of a network after leader election."""
	if group_id not in groups:
		return ValueError(f"Group {group_id} not found.")
	
	current_leader = groups[group_id]["leader_ip"]
	if current_leader and liveness(current_leader, port):
		return Exception("Leader is alive.")
	
	groups[group_id]["leader_ip"] = new_leader_ip
	return Response(success=True, message="Leader update successful")


@dispatcher.public
def get_group_leader(group_id):
	"""Gets the current leader of a group."""
	if group_id not in groups:
		return ValueError(f"Group {group_id} not found.")
	
	current_leader = groups[group_id]["leader_ip"]
	return current_leader


@dispatcher.public
def liveness(ip, port):
	"""Liveness check that a node is alive."""
	try:
		with socket.create_connection((ip, port), timeout=2):
			return True
	except (socket.timeout, socket.error):
		return False



if __name__ == "__main__":
	serve(5000)
