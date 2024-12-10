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
from tinyrpc.transports.http import HttpPostClientTransport
from tinyrpc import RPCClient
import threading
import time

from structs.generic import Response
from structs.nds import (
	NDS_Group,
	FetchGroupResponse,
	CreateGroupResponse,
	NDS_HeartbeatResponse,
	UpdateGroupResponse,
)

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
overseer_cycles_timeout = 6

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


def create_rpc_client(ip, port):
	"""
	Create a remote client object.
	This itself does not attempt to send anything, so it cannot fail.
	"""
	rpc_client = RPCClient(
		JSONRPCProtocol(), HttpPostClientTransport(f"http://{ip}:{port}/", timeout=5)
	)
	return rpc_client


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
				if new_val > overseer_cycles_timeout:
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


### LEADER ELECTION


@dispatcher.public
def update_group_leader(group_id):
	"""Updates a leader of a network after leader election."""
	global leader_port
	new_leader_ip = get_ip()
	if group_id not in groups:
		return UpdateGroupResponse(
			ok=False, message=f"Group {group_id} not found.", group=None
		).to_json()

	group = groups[group_id]
	current_leader_ip = group.leader_ip

	try:
		rpc_client = create_rpc_client(current_leader_ip, leader_port)
		leader = rpc_client.get_proxy()
		response: Response = Response.from_json(leader.still_leader_of_group(group_id))

		if current_leader_ip and response.ok:
			return UpdateGroupResponse(
				ok=False, message="Leader is still alive, cannot update.", group=group
			).to_json()

		group.leader_ip = new_leader_ip
		groups[group_id] = group
		return UpdateGroupResponse(ok=True, message="ok", group=group).to_json()
	except Exception as e:
		group.leader_ip = new_leader_ip
		groups[group_id] = group
		return UpdateGroupResponse(ok=True, message="ok", group=group).to_json()


if __name__ == "__main__":
	logging.basicConfig(filename="nds.log", level=logging.INFO)
	serve()
