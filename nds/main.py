import socket
import uuid
import gevent
import gevent.pywsgi
import gevent.queue
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher
from sqlitedict import SqliteDict


dispatcher = RPCDispatcher()
groups = None
leader_port = 50001
nds_port = 50002


class Response:
	def __init__(self, success: bool, message: str, data=None):
		self.success = success
		self.message = message
		self.data = data

	def __repr__(self):
		return f"Response(success={self.success}, message='{self.message}', data={self.data})"

	def to_dict(self):
		return {"success": self.success, "message": self.message, "data": self.data}


@dispatcher.public
def reset_database():
	"""Reset the groups database."""
	groups.clear()
	groups.sync()
	return {"success": True, "message": "Database reset successfully"}


def serve(ip="0.0.0.0", port=50002, db_path="groups.db", reset_db=False):
	global groups
	if groups is None:
		groups = SqliteDict(db_path, autocommit=True)
	if reset_db:
		groups.clear()

	transport = WsgiServerTransport(queue_class=gevent.queue.Queue)
	wsgi_server = gevent.pywsgi.WSGIServer((ip, port), transport.handle)
	gevent.spawn(wsgi_server.serve_forever)
	rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
	print(f"NDS listening at {ip} on port {port}")
	rpc_server.serve_forever()


@dispatcher.public
def create_group(leader_ip, group_name):
	"""Create a new chat."""
	group_id = str(uuid.uuid4())
	print(f"Creating a group {group_name}")
	groups[group_id] = {
		"leader_ip": leader_ip,
		"group_id": group_id,
		"group_name": group_name,
	}
	print(f"Group creation successful.")
	return Response(
		success=True, message="Chat creation successful", data={"group_id": group_id}
	).to_dict()


@dispatcher.public
def get_groups():
	"""Get all possible chats to join."""
	group_list = list(groups.values())
	return Response(
		success=True, message="Groups fetched successfully", data={"groups": group_list}
	).to_dict()


@dispatcher.public
def update_group_leader(group_id, new_leader_ip):
	"""Updates a leader of a network after leader election."""
	global leader_port
	if group_id not in groups:
		return Response(success=False, message=f"Group {group_id} not found.").to_dict()

	group = groups[group_id]
	current_leader = group["leader_ip"]
	if current_leader and liveness(current_leader, leader_port):
		return Response(
			success=False, message="Leader is still alive, cannot update."
		).to_dict()

	group["leader_ip"] = new_leader_ip
	groups[group_id] = group
	return Response(success=True, message="Leader update successful").to_dict()


@dispatcher.public
def get_group_leader(group_id):
	"""Gets the current leader of a group."""
	if group_id not in groups:
		return Response(success=False, message=f"Group {group_id} not found.").to_dict()
	group = groups[group_id]
	current_leader = group["leader_ip"]
	return Response(
		success=True,
		message="Group leader fetched successfully",
		data={"leader_ip": current_leader},
	).to_dict()


@dispatcher.public
def liveness(ip, port):
	"""Liveness check that a node is alive."""
	try:
		with socket.create_connection((ip, port), timeout=2):
			return True
	except (socket.error, Exception):
		return False


if __name__ == "__main__":
	serve()
