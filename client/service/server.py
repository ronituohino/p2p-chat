import uuid
import logging
import gevent
import gevent.pywsgi
import gevent.queue
import threading
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher

from client.service import leader_election
from client.service.heartbeat import start_heartbeat
from client.service.messaging import message_broadcast, send_message_to_peer
from client.service.synchronization import store_message, synchronize_with_leader
from structs.client import (
	Group,
	Node,
	JoinGroupResponse,
	ReceiveMessageResponse,
	HeartbeatResponse,
	ReportLogicalClockResponse,
	CallForSynchronizationResponse,
	UpdateMessagesResponse,
)
from structs.generic import Response
from structs.nds import FetchGroupResponse, CreateGroupResponse
from client.service.state import AppState
from client.service.crawler import start_crawler
from client.service.overseer import start_overseer
from client.service.synchronization import maintain_received_messages
# This needs the server to be on one thread, otherwise IPs will get messed up

app = AppState()
dispatcher = RPCDispatcher()
app.dispatcher = dispatcher
app.leader_election = leader_election


# Custom WSGI app to handle IP extraction
class CustomWSGITransport(WsgiServerTransport):
	def handle(self, environ, start_response):
		app.env = environ
		return super().handle(environ, start_response)


def serve(net=None, node_name=None):
	app.name = node_name
	app.networking = net

	transport = CustomWSGITransport(queue_class=gevent.queue.Queue)
	wsgi_server = gevent.pywsgi.WSGIServer(("0.0.0.0", app.node_port), transport.handle)
	gevent.spawn(wsgi_server.serve_forever)

	rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
	rpc_server.serve_forever()

	cleanup_thread = threading.Thread(
		target=maintain_received_messages, args=(app,), daemon=True
	)

	cleanup_thread.start()
	logging.info("Server is running")


def add_node_discovery_source(nds_ip):
	"""
	Adds a discovery server, and returns all possible groups to join from NDS or None, if the connection fails.
	"""
	remote_server = app.create_rpc_client(ip=nds_ip, port=app.nds_port)
	app.nds_servers[nds_ip] = remote_server

	try:
		response: FetchGroupResponse = FetchGroupResponse.from_json(
			remote_server.get_groups()
		)
		if response.ok:
			start_crawler(app)
			return response.groups
		else:
			logging.error("Failed to add NDS")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to add NDS {e}")
		return None


### GROUP JOINING / LEAVING


def create_group(group_name, nds_ip) -> Group | None:
	"""Create a new group and register it with NDS,
	  making this peer the leader.

	Raises:
		ValueError: Error if NDS Server does not exists.
		ValueError: Error if the group name has not been set

	Returns:
		Group obj: newly created group
	"""
	remote_server = app.nds_servers.get(nds_ip, False)
	if not remote_server:
		logging.error(f"NDS server with IP {nds_ip} does not exist.")
		return None

	if not group_name:
		logging.error("Group name cannot be empty.")
		return None

	try:
		response: CreateGroupResponse = CreateGroupResponse.from_json(
			remote_server.create_group(group_name=group_name)
		)

		if response.ok:
			group_id = response.group.group_id
			this_node = Node(node_id=0, name=app.name, ip=response.group.leader_ip)
			this_group = Group(
				group_id=group_id,
				name=group_name,
				nds_ip=nds_ip,
				self_id=0,
				leader_id=0,
				peers={0: this_node},
			)

			app.active_group = this_group
			start_overseer(app)

			logging.info(f"Created group, {group_name}, with ID: {group_id}")
			return this_group
		else:
			logging.error("Failed to create group")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to create group: {e}")
		return None


app.create_group = create_group


def request_to_leave_group(group: Group):
	"""A way for client to leave a group."""

	# If we are the leader of the group
	# we can just dip, and stop responding to messages

	# If we are not the leader
	# we can just stop sending liveness pings to leader
	# who then notices that we are gone

	logging.info("Leaving group.")
	if app.active_group and group.group_id == app.active_group.group_id:
		app.active_group = None
		app.networking.refresh_group(group)


def request_to_join_group(leader_ip, group_id) -> Group | None:
	"""
	Args:
		leader_ip (str): An IP addr. of the leader ip
		group_id (str): An ID of the group.

	Returns:
		list: A set of nodes if success.
	"""
	remote_server = app.create_rpc_client(leader_ip, app.node_port)
	# This is request to leader
	try:
		app.logical_clock = 0
		response: JoinGroupResponse = JoinGroupResponse.from_json(
			remote_server.join_group(app.name, group_id)
		)
		if response.ok:
			app.active_group = response.group
			app.active_group.self_id = response.assigned_peer_id
			logging.info(f"Joined group: {response.group}")
			start_heartbeat(app)
			synchronize_with_leader(app)
			return response.group
		else:
			logging.error(f"Failed to join group with error: {response.message}")
			group = app.active_group
			app.networking.refresh_group(group)
			return None
	except ConnectionError as e:
		logging.error(f"EXC: Failed to join group: {e}")
		return None


app.request_to_join_group = request_to_join_group


@dispatcher.public
def join_group(peer_name, group_id):
	"""
	This is called when a client asks the group leader if they could join.

	Args:
		group_id (str): UID of the group.
		peer_name (peer_name): name of the peer node.

	Returns:
		response: If success return data of the group.
	"""

	logging.info(f"Peer {peer_name} requesting to join group.")
	try:
		group = app.active_group

		if not group:
			return JoinGroupResponse(
				ok=False, message="not-in-any-group", assigned_peer_id=-1, group=None
			).to_json()

		peer_ip = app.get_ip()

		if group.leader_id != group.self_id:
			return JoinGroupResponse(
				ok=False, message="not-leader", assigned_peer_id=-1, group=None
			).to_json()

		if group.group_id != group_id:
			return JoinGroupResponse(
				ok=False, message="not-in-that-group", assigned_peer_id=-1, group=None
			).to_json()

		for peer in group.peers.values():
			if peer.name == peer_name and peer.ip == peer_ip:
				# Overseeing
				app.last_node_response[peer.node_id] = 0
				return JoinGroupResponse(
					ok=True,
					message="already-in-group",
					assigned_peer_id=peer.node_id,
					group=group,
				).to_json()

		assigned_peer_id = max(group.peers.keys(), default=0) + 1

		# Overseeing
		app.last_node_response[assigned_peer_id] = 0
		group.peers[assigned_peer_id] = Node(
			node_id=assigned_peer_id, name=peer_name, ip=peer_ip
		)
		app.networking.refresh_group(group)
		logging.info(f"Peer {assigned_peer_id} joined with IP {peer_ip}")
		return JoinGroupResponse(
			ok=True, message="ok", group=group, assigned_peer_id=assigned_peer_id
		).to_json()

	except Exception as e:
		logging.error(f"Error in join_group: {e}")
		return JoinGroupResponse(
			ok=False, message="error", group=None, assigned_peer_id=0
		).to_json()


def send_message(msg) -> bool:
	"""Send a message to be broadcasted by leader, called from ui.
	Args:
		msg (str): the message.

	Returns:
		bool: If message was sent successfully.
	"""
	if not app.active_group:
		return False

	group = app.active_group
	leader_ip = app.active_group.peers[app.active_group.leader_id].ip
	msg_id = str(uuid.uuid4())

	store_message(
		app,
		msg,
		msg_id,
		group.group_id,
		group.self_id,
		app.logical_clock,
	)

	logging.info(f"Networking message to leader {leader_ip}")
	if group.self_id == group.leader_id:
		# We are the leader, broadcast to others
		logging.info("We are leader, broadcast")

		app.logical_clock += 1
		return message_broadcast(
			app, msg, msg_id, group.group_id, group.self_id
		)
	elif leader_ip:
		# We are not the leader, send to leader who broadcasts to others
		logging.info("We are not leader, broadcast through leader")
		return send_message_to_peer(
			app=app,
			client_ip=leader_ip,
			msg=msg,
			msg_id=msg_id,
			group_id=app.active_group.group_id,
			source_id=app.active_group.self_id,
			logical_clock=app.logical_clock,
		)
	else:
		logging.error(
			f"IP for leader {leader_ip} in group {app.active.group_id} does not exist."
		)
		return False


@dispatcher.public
def receive_message(msg, msg_id, group_id, source_id, leader_logical_clock=0):
	"""Handle receiving a message from peer.
	If message is meant for current node, then it will store it, otherwise it will
	broadcast it forward.

	Args:
		msg (str): the message.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
		source_id (str): ID of the source peer.

	Returns:
		response: success / fail
	"""
	group = app.active_group
	if not group or group.group_id != group_id:
		logging.warning("Couldn't receive a message, no longer in group.")
		return ReceiveMessageResponse(ok=False, message="no-longer-in-group").to_json()
	if msg_id in app.received_messages:
		logging.warning("Couldn't receive a message, duplicate.")
		return ReceiveMessageResponse(ok=True, message="duplicate").to_json()

	if (
		leader_logical_clock > app.logical_clock + 1
		and group.leader_id != group.self_id
	):
		logging.warning("Detected missing messages. Initiating synchronization.")
		try:
			synchronize_with_leader(app)
		except Exception as e:
			logging.error(f"Error during synchronization with leader: {e}")

	current_logical_clock = max(app.logical_clock, leader_logical_clock) + 1
	app.logical_clock = current_logical_clock

	logging.info("Storing the message...")
	try:
		store_message(app, msg, msg_id, group_id, source_id, current_logical_clock)
	except Exception as e:
		logging.error(f"Error storing the message: {e}")
		return ReceiveMessageResponse(
			ok=False, message="store-message-failed"
		).to_json()

	if group.self_id == group.leader_id:
		logging.info("Broadcasting the message forward.")
		try:
			message_broadcast(app, msg, msg_id, group_id, source_id)
		except Exception as e:
			logging.error(f"Error broadcasting the message: {e}")
			ReceiveMessageResponse(ok=False, message="store-message-failed").to_json()
	return ReceiveMessageResponse(ok=True, message="ok").to_json()


@dispatcher.public
def receive_heartbeat(peer_id, group_id):
	with app.overseer_lock:
		active = app.active_group
		if active.group_id != group_id:
			return HeartbeatResponse(
				ok=False, message="changed-group", peers=None, logical_clock=0
			).to_json()

		if peer_id in active.peers:
			app.last_node_response[peer_id] = 0
			return HeartbeatResponse(
				ok=True,
				message="ok",
				peers=active.peers,
				logical_clock=app.logical_clock,
			).to_json()

		return HeartbeatResponse(
			ok=False, message="you-got-kicked-lol", peers=None, logical_clock=0
		).to_json()


@dispatcher.public
def report_logical_clock(group_id):
	group = app.active_group
	if group_id == group.group_id:
		return ReportLogicalClockResponse(
			ok=True,
			message="Logical clock reported succesfully.",
			data={"logical_clock": app.logical_clock},
		).to_json()


@dispatcher.public
def election_message(group_id, candidate_id):
	group = app.active_group
	if group_id == group.group_id:
		self_id = group.self_id
		if self_id < candidate_id:
			leader_election(app, group_id)
			return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


@dispatcher.public
def still_leader_of_group(group_id):
	"""Check if still a leader of the group."""
	group = app.active_group
	if group and group.group_id == group_id and group.leader_id == group.self_id:
		return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


@dispatcher.public
def update_leader(group_id, new_leader_id):
	"""Update the new leader."""
	group = app.active_group
	if group and group.group_id == group_id:
		group.leader_id = new_leader_id
		return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


@dispatcher.public
def call_for_synchronization(group_id, peer_logical_clock):
	logging.info("Calling for synchronization.")
	group = app.active_group
	if group_id != group.group_id:
		return CallForSynchronizationResponse(
			ok=False, message="This is the wrong group.", data={}
		).to_json()

	all_messages = app.message_store.get(group_id, [])
	missing_messages = [
		msg for msg in all_messages if msg["logical_clock"] > peer_logical_clock
	]

	return CallForSynchronizationResponse(
		ok=True,
		message="Missing messages sent.",
		data={"missing_messages": missing_messages},
	).to_json()


@dispatcher.public
def update_messages(group_id, messages):
	group = app.active_group

	if group_id == group.group_id:
		for msg_data in messages:
			if msg_data["msg_id"] not in app.received_messages:
				store_message(
					app,
					msg_data["msg"],
					msg_data["msg_id"],
					group_id,
					msg_data["source_id"],
					msg_data["logical_clock"],
				)
		if messages:
			max_logical_clock = max(msg["logical_clock"] for msg in messages)
			app.logical_clock = max(app.logical_clock, max_logical_clock)
		return UpdateMessagesResponse(ok=True).to_json()
	return UpdateMessagesResponse(ok=False).to_json()


if __name__ == "__main__":
	serve()
