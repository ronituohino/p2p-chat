import socket
import uuid
import gevent
import logging
import gevent.pywsgi
import gevent.queue
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher
import threading
import time

from structs.nds import (
	NDS_Group,
	FetchGroupResponse,
	CreateGroupResponse,
	NDS_HeartbeatResponse,
)
from structs.generic import Response

# This needs the server to be on one thread, otherwise IPs will get messed up
env = None


# Custom WSGI app to handle IP extraction
class CustomWSGITransport(WsgiServerTransport):
	def handle(self, environ, start_response):
		global env
		env = environ
		return super().handle(environ, start_response)


def get_ip():
	return env.get("REMOTE_ADDR", "Unknown IP")


# Constants
leader_port = 50001
nds_port = 50002
overseer_interval = 1

# Runtime constants
dispatcher = RPCDispatcher()
overseer: threading.Thread = None

# Global variables
groups: dict[str, NDS_Group] = {}  # key is group_id
last_leader_response: dict[
	str, int
] = {}  # key is group_id, used to check when last heard from group, value is the overseer cycles


def serve(ip="0.0.0.0", port=nds_port):
	transport = CustomWSGITransport(queue_class=gevent.queue.Queue)
	wsgi_server = gevent.pywsgi.WSGIServer((ip, port), transport.handle)
	gevent.spawn(wsgi_server.serve_forever)
	rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
	init_overseer()

	status = f"NDS listening at {ip} on port {port}."
	print(status)
	logging.info(status)
	rpc_server.serve_forever()


### GROUP MANAGEMENT


@dispatcher.public
def get_groups():
	"""Return a list of all possible Groups to join."""
	group_list = list(groups.values())
	logging.info(f"Groups sent: {group_list}")
	return FetchGroupResponse(ok=True, groups=group_list).to_json()


@dispatcher.public
def create_group(group_name):
	"""Create a new chat."""
	group_id = str(uuid.uuid4())
	logging.info(f"Creating group: {group_name}")
	new_group = NDS_Group(group_id=group_id, name=group_name, leader_ip=get_ip())
	groups[group_id] = new_group
	last_leader_response[group_id] = 0
	logging.info(f"Group creation successful for {group_name}")
	return CreateGroupResponse(ok=True, group=new_group).to_json()


### HEARTBEAT


@dispatcher.public
def receive_heartbeat(group_id):
	if group_id in groups and group_id in last_leader_response:
		logging.info(f"Group {group_id} heartbeat received.")
		last_leader_response[group_id] = 0
		return NDS_HeartbeatResponse(ok=True, message="ok").to_json()
	else:
		return NDS_HeartbeatResponse(
			ok=False, message="group-deleted-womp-womp"
		).to_json()


### OVERSEEING


def init_overseer():
	global overseer
	overseer = threading.Thread(target=overseer_thread, daemon=True)
	logging.info("Overseer started.")
	overseer.start()


def overseer_thread():
	try:
		while True:
			logging.info("Overseeing groups.")
			groups_to_delete = []

			for group_id in last_leader_response.keys():
				new_val = last_leader_response[group_id] + 1
				if new_val > 10:
					# If have not received heartbeat from group leader in 10 cycles, delete Group
					groups_to_delete.append(group_id)
				else:
					last_leader_response[group_id] = new_val

			for group_id in groups_to_delete:
				del last_leader_response[group_id]
				del groups[group_id]
				logging.info(f"Group {group_id} deleted -- no heartbeat from leader")

			time.sleep(overseer_interval)

	finally:
		logging.info("Killing overseer.")


### THINGS BELOW ARE NOT INTEGRATED YET


@dispatcher.public
def reset_database():
	"""Reset the groups database."""
	global groups
	groups = {}
	return {"success": True, "message": "Database reset successfully"}


@dispatcher.public
def update_group_leader(group_id):
	"""Updates a leader of a network after leader election."""
	global leader_port
	new_leader_ip = get_ip()
	if group_id not in groups:
		return Response(success=False, message=f"Group {group_id} not found.")

	group = groups[group_id]
	current_leader = group["leader_ip"]
	if current_leader and liveness(current_leader, leader_port):
		return Response(
			success=False,
			message="Leader is still alive, cannot update.",
			data={"leader_ip": current_leader},
		)

	group["leader_ip"] = new_leader_ip
	groups[group_id] = group

	logging.info("Leader update successful.")
	return Response(success=True, message="Leader update successful")


@dispatcher.public
def remove_group(group_id):
	"""Remove a group of a network."""
	if group_id in groups:
		groups.pop(group_id)
		logging.info(f"Group {group_id} has been removed.")
		return Response(success=True, message=f"Group {group_id} has been removed.")
	else:
		logging.info(f"Group {group_id} was not found.")
		return Response(success=True, message=f"Group {group_id} was not found.")


@dispatcher.public
def get_group_leader(group_id):
	"""Gets the current leader of a group."""
	if group_id not in groups:
		return Response(success=False, message=f"Group {group_id} not found.")
	group = groups[group_id]
	current_leader = group["leader_ip"]
	logging.info("Group leader sent successfully.")
	return Response(
		success=True,
		message="Group leader fetched successfully",
		data={"leader_ip": current_leader},
	)


@dispatcher.public
def liveness(ip, port):
	"""Liveness check that a node is alive."""
	try:
		with socket.create_connection((ip, port), timeout=2):
			return True
	except (socket.error, Exception):
		return False


if __name__ == "__main__":
	logging.basicConfig(filename="nds.log", level=logging.INFO)
	serve()
