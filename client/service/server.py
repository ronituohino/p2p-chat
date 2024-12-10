import uuid
import random
import logging
import threading
import time
import gevent
import gevent.pywsgi
import gevent.queue
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher
from tinyrpc.transports.http import HttpPostClientTransport
from tinyrpc import RPCClient

from structs.client import (
	Group,
	Node,
	Message,
	JoinGroupResponse,
	ReceiveMessageResponse,
	HeartbeatResponse,
	UpdateGroupResponse,
)
from structs.generic import Response
from structs.nds import FetchGroupResponse, CreateGroupResponse, NDS_HeartbeatResponse

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
node_port = 50001
nds_port = 50002

heartbeat_min_interval = 2
heartbeat_max_interval = 4

overseer_interval = 1
overseer_cycles_timeout = 10

# Runtime constants
dispatcher = RPCDispatcher()
self_name = None
networking = None

# Global variables
nds_servers: dict[str, RPCClient] = {}  # key is nds_ip
active_group: Group = None  # we can only be in one group at a time


def get_active_group() -> Group:
	global active_group
	return active_group


def set_active_group(group: Group):
	global active_group
	active_group = group


message_store: dict[str, Message] = {}  # key is group_id
received_messages = set()

### SERVER STARTUP, RPC CONNECTIONS, NDS ADDITION


def serve(net=None, node_name=None):
	global self_name
	self_name = node_name
	global networking
	networking = net

	transport = CustomWSGITransport(queue_class=gevent.queue.Queue)
	wsgi_server = gevent.pywsgi.WSGIServer(("0.0.0.0", node_port), transport.handle)
	gevent.spawn(wsgi_server.serve_forever)

	rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
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


def add_node_discovery_source(nds_ip):
	"""
	Adds a discovery server, and returns all possible groups to join from NDS or None, if the connection fails.
	"""
	rpc_client = create_rpc_client(ip=nds_ip, port=nds_port)
	nds_servers[nds_ip] = rpc_client

	try:
		nds = rpc_client.get_proxy()
		response: FetchGroupResponse = FetchGroupResponse.from_json(nds.get_groups())
		if response.ok:
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
	rpc_client = nds_servers.get(nds_ip, False)
	if not rpc_client:
		raise ValueError(f"NDS server with IP {nds_ip} does not exist.")

	if not group_name:
		raise ValueError("Group name cannot be empty.")

	try:
		nds = rpc_client.get_proxy()
		response: CreateGroupResponse = CreateGroupResponse.from_json(
			nds.create_group(group_name=group_name)
		)

		if response.ok:
			group_id = response.group.group_id
			this_node = Node(node_id=0, name=self_name, ip=response.group.leader_ip)
			this_group = Group(
				group_id=group_id,
				name=group_name,
				vector_clock=0,
				nds_ip=nds_ip,
				self_id=0,
				leader_id=0,
				peers={0: this_node},
			)
			set_active_group(this_group)

			start_heartbeat()
			start_overseer()

			logging.info(f"Created group, {group_name}, with ID: {group_id}")
			return this_group
		else:
			logging.error("Failed to create group")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to create group: {e}")
		return None


def leave_group(group_id: str):
	"""A way for client to leave a group."""

	active = get_active_group()
	if not active or active.group_id != group_id:
		logging.error(f"Cannot leave group {group_id} because it's not active")
		return

	# If we are the leader of the group
	# we can just dip, and stop responding to messages

	# If we are not the leader
	# we can just stop sending liveness pings to leader
	# who then notices that we are gone

	logging.info("Leaving group.")
	set_active_group(None)


def request_to_join_group(leader_ip) -> Group | None:
	"""
	Args:
		leader_ip (str): An IP addr. of the leader ip
		group_id (str): An ID of the group.

	Returns:
		list: A set of nodes if success.
	"""
	rpc_client = create_rpc_client(leader_ip, node_port)
	# This is request to leader
	try:
		leader = rpc_client.get_proxy()
		response: JoinGroupResponse = JoinGroupResponse.from_json(
			leader.join_group(self_name)
		)
		if response.ok:
			response.group.self_id = response.assigned_peer_id
			set_active_group(response.group)
			logging.info(f"Joined group: {response.group}")

			start_heartbeat()

			# synchronize_with_leader(group_id)
			return response.group
		else:
			logging.error(f"Failed to join group with error: {response.message}")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to join group: {e}")
		return None


@dispatcher.public
def join_group(peer_name):
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
		group = get_active_group()
		peer_ip = get_ip()

		if group.leader_id != group.self_id:
			return JoinGroupResponse(
				ok=False, message="not-leader", assigned_peer_id=0, group=None
			).to_json()

		for peer in group.peers.values():
			if peer.name == peer_name:
				return JoinGroupResponse(
					ok=False, message="already-in-group", assigned_peer_id=0, group=None
				).to_json()
			if peer.ip == peer_ip:
				return JoinGroupResponse(
					ok=False, message="ip-taken", assigned_peer_id=0, group=None
				).to_json()

		assigned_peer_id = max(group.peers.keys(), default=0) + 1
		group.peers[assigned_peer_id] = Node(
			node_id=assigned_peer_id, name=peer_name, ip=peer_ip
		)

		# Overseeing
		last_node_response[assigned_peer_id] = 0

		networking.refresh_group(group)
		logging.info(f"Peer {assigned_peer_id} joined with IP {peer_ip}")

		return JoinGroupResponse(
			ok=True, message="ok", group=group, assigned_peer_id=assigned_peer_id
		).to_json()
	except Exception as e:
		logging.error(f"Error in join_group: {e}")
		return JoinGroupResponse(
			ok=False, message="error", group=None, assigned_peer_id=0
		).to_json()


### MESSAGING


def send_message(msg) -> bool:
	"""Send a message to be broadcasted by leader, called from ui.
	Args:
		msg (str): the message.

	Returns:
		bool: If message was sent successfully.
	"""

	active = get_active_group()
	if not active:
		return False

	leader_ip = active.peers[active.leader_id].ip
	msg_id = str(uuid.uuid4())

	logging.info(f"Networking message to leader {leader_ip}")

	if active.self_id == active.leader_id:
		# We are the leader, broadcast to others
		logging.info("We are leader, broadcast")
		return message_broadcast(msg, msg_id, active.group_id, active.self_id)
	elif leader_ip:
		# We are not the leader, send to leader who broadcasts to others
		logging.info("We are not leader, broadcast through leader")
		rpc_client = create_rpc_client(leader_ip, node_port)
		return send_message_to_peer(
			client=rpc_client, msg=msg, msg_id=msg_id, group_id=active.group_id
		)
	else:
		logging.error(
			f"IP for leader {leader_ip} in group {active.group_id} does not exist."
		)
		return False


def send_message_to_peer(client, msg, msg_id, group_id):
	"""Send a message to individual targeted peer.

	Args:
		client (object): The rpc_client to the peer.
		msg (str): the message.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
	"""
	try:
		source_id = get_active_group().self_id
		peer = client.get_proxy()
		response: ReceiveMessageResponse = ReceiveMessageResponse.from_json(
			peer.receive_message(
				msg=msg, msg_id=msg_id, group_id=group_id, source_id=source_id
			)
		)
		if response.ok:
			return True
		if not response.ok:
			logging.info(f"Failed to send message: {response.message}")
			return False
	except BaseException as e:
		logging.info(f"Failed to send message: {e}")
		return False


@dispatcher.public
def receive_message(msg, msg_id, group_id, source_id):
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
	group = get_active_group()

	if not group or group.group_id != group_id:
		return ReceiveMessageResponse(ok=False, message="no-longer-in-group").to_json()
	if msg_id in received_messages:
		return ReceiveMessageResponse(ok=False, message="duplicate").to_json()

	# if vector_clock > current_vector_clock + 1:
	# logging.warning("Detected missing messages. Initiating synchronization.")
	# synchronize_with_leader(group_id)

	# current_vector_clock = max(current_vector_clock, vector_clock) + 1
	# update_group_info(
	# group_id=group_id,
	# group_name=group_name,
	# self_id=self_id,
	# leader_id=leader_id,
	# vector_clock=current_vector_clock,
	# peers=peers,
	# )

	peer = group.peers[source_id]

	received_messages.add(msg_id)
	networking.receive_message(source_name=peer.name, msg=msg)
	# store_message(msg, msg_id, group_id, source_id, 0)

	if group.self_id == group.leader_id:
		message_broadcast(msg, msg_id, group_id, source_id)
	return ReceiveMessageResponse(ok=True, message="ok").to_json()


def message_broadcast(msg, msg_id, group_id, source_id) -> bool:
	"""Broadcast a message as leader to other peers

	Args:
		msg (str): A message that user want to send.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
		source_id (str): Peer ID where the message came from.

	Returns:
		bool: If message was sent successfully.
	"""
	group = get_active_group()
	peers = list(group.peers.values())
	other_peers = []
	for p in peers:
		if p.node_id != source_id and p.node_id != group.self_id:
			other_peers.append(p)

	if len(other_peers) < 1:
		logging.info(f"No other peers found for group {group_id}.")
		return False

	# vector_clock += 1
	# msg = (vector_clock, msg)
	# update_group_info(
	# group_id=group_id,
	# group_name=group_name,
	# self_id=self_id,
	# leader_id=leader_id,
	# vector_clock=vector_clock,
	# peers=peers,
	# )

	logging.info(f"Broadcasting message to peers: {peers}")
	for peer in other_peers:
		rpc_client = create_rpc_client(peer.ip, node_port)
		send_message_to_peer(rpc_client, msg, msg_id, group_id)
	return True


### HEARTBEAT

# thread that sends rpc to leader or NDS every now and then
heartbeat: threading.Thread = None
heartbeat_counter = 0  # set to the id of the heartbeat
heartbeat_kill_flags = set()


def start_heartbeat():
	global heartbeat
	global heartbeat_counter
	global heartbeat_kill_flags

	if heartbeat:
		# Kill existing heartbeat
		logging.info(f"Killing heartbeat {heartbeat_counter}")
		heartbeat_kill_flags.add(heartbeat_counter)

	logging.info("Starting heartbeat sending.")
	heartbeat_counter += 1
	heartbeat = threading.Thread(
		target=heartbeat_thread, args=(heartbeat_counter,), daemon=True
	)
	heartbeat.start()


def heartbeat_thread(hb_id: int):
	global heartbeat_kill_flags

	# Wrap in try clause, so that can be closed with .raise_exception()
	try:
		while True:
			if hb_id in heartbeat_kill_flags:
				raise InterruptedError

			active = get_active_group()

			if not active:
				raise InterruptedError

			# If this node not leader, send heartbeat to leader
			if active.self_id != active.leader_id:
				leader_ip = active.peers[active.leader_id].ip
				if leader_ip:
					try:
						rpc_client = create_rpc_client(leader_ip, node_port)
						leader = rpc_client.get_proxy()
						logging.info(
							f"Sending heartbeat to leader from {active.self_id}."
						)
						response: HeartbeatResponse = HeartbeatResponse.from_json(
							leader.receive_heartbeat(active.self_id)
						)
						if response.ok:
							logging.info("Refreshing peers.")
							active.peers = response.peers
							networking.refresh_group(active)
						else:
							logging.warning("Leader said not ok, we got kicked!")
							set_active_group(None)
							networking.refresh_group(None)
					except Exception as e:
						logging.info(f"Exception caught: {e}")
						try:
							leader_election(active.group_id)
						except Exception as ea:
							logging.info(f"what {ea}")
						logging.error(f"EXC: Error sending hearbeat to leader: {e}")
				else:
					leader_election(active.group_id)
					logging.error("Leader IP not found, initiating election...")
			else:
				# This node is leader, send heartbeat to NDS
				rpc_client = nds_servers[active.nds_ip]
				try:
					nds = rpc_client.get_proxy()
					logging.info("Sending heartbeat to NDS.")
					response: NDS_HeartbeatResponse = NDS_HeartbeatResponse.from_json(
						nds.receive_heartbeat(active.group_id)
					)
					if not response.ok:
						if response.message == "group-deleted-womp-womp":
							logging.error("NDS deleted the group :(")
							set_active_group(None)
							networking.refresh_group(None)
						else:
							logging.error("NDS rejected heartbeat?")
				except BaseException as e:
					logging.error(f"EXC: Failed to send heartbeat to NDS: {e}")

			# Sleep for a random interval, balances out leader election more
			interval = random.uniform(heartbeat_min_interval, heartbeat_max_interval)
			time.sleep(interval)
	finally:
		logging.info("Killing heartbeat.")


@dispatcher.public
def receive_heartbeat(peer_id):
	active = get_active_group()
	if peer_id in active.peers:
		last_node_response[peer_id] = 0
		return HeartbeatResponse(
			ok=True, message="ok", peers=active.peers, vector_clock=active.vector_clock
		).to_json()
	else:
		return HeartbeatResponse(
			ok=False, message="you-got-kicked-lol", peers=None, vector_clock=0
		).to_json()


### OVERSEEING

# thread that checks which nodes have sent heartbeat to me (leader) every now and then
overseer: threading.Thread = None
overseer_counter = 0  # set to the id of the heartbeat
overseer_kill_flags = set()

last_node_response: dict[
	str, int
] = {}  # key is node_id, used to check when last heard from node, value is the overseer cycles


def start_overseer():
	"""Starts overseeing thread, used by leader to monitor heartbeats from followers, and deletes those who are not active"""
	global overseer
	global overseer_counter
	global overseer_kill_flags

	if overseer:
		# Kill existing heartbeat
		logging.info(f"Killing overseer {overseer_counter}.")
		overseer_kill_flags.add(overseer_counter)

	logging.info("Starting overseer.")
	overseer_counter += 1
	overseer = threading.Thread(
		target=overseer_thread, args=(overseer_counter,), daemon=True
	)
	overseer.start()


def overseer_thread(ov_id: int):
	try:
		while True:
			if ov_id in overseer_kill_flags:
				raise InterruptedError

			active = get_active_group()
			if not active:
				raise InterruptedError

			nodes_to_delete = []
			for node_id in last_node_response.keys():
				new_val = last_node_response[node_id] + 1
				if new_val > 10:
					# If have not received heartbeat from group leader in 10 cycles, delete Group
					nodes_to_delete.append(node_id)
				else:
					last_node_response[node_id] = new_val

			for node_id in nodes_to_delete:
				del last_node_response[node_id]
				del active.peers[node_id]
				logging.info(f"Node {node_id} deleted -- no heartbeat from node.")

			networking.refresh_group(active)
			time.sleep(overseer_interval)
	except Exception as e:
		logging.error(f"EXC: Overseer failed {e}")
	finally:
		logging.info("Overseer killed.")


### LEADER ELECTION


def leader_election(group_id):
	logging.info("Starting leader election.")
	active_group = get_active_group()
	peers = active_group.peers
	self_id = active_group.self_id
	vector_clock = active_group.vector_clock

	low_id_nodes = [peer_id for peer_id in peers if peer_id < self_id]
	got_answer = None
	if not low_id_nodes:
		logging.info("No other nodes found, making self leader.")
		become_leader()
	else:
		for peer_id in low_id_nodes:
			peer = peers[peer_id]
			peer_ip = peer.ip

			logging.info(f"Pinging {peer_id} if they want to be leader...")
			try:
				rpc_client = create_rpc_client(peer_ip, node_port)
				remote_server = rpc_client.get_proxy()
				response: Response = Response(
					remote_server.election_message(group_id, self_id, vector_clock)
				).to_json()

				if response.ok:
					logging.info(
						f"{peer_id} responded that they can be leader. Stopping election."
					)
					got_answer = True
			except Exception:
				logging.info(f"No response from {peer_id}.")
				continue
		if not got_answer:
			logging.info("No response from other nodes, making self leader.")
			become_leader()


@dispatcher.public
def election_message(group_id, candidate_id, candidate_vc):
	group = get_active_group()
	if group_id == group.group_id:
		self_id = group.self_id
		vector_clock = group.vector_clock
		if self_id < candidate_id and vector_clock >= candidate_vc:
			leader_election(group_id)
			return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


def become_leader():
	group = get_active_group()
	self_id = group.self_id

	logging.info("Pinging NDS that we want to be leader.")
	did_update, new_nds_group = update_nds_server()

	if did_update and new_nds_group:
		logging.info("NDS made us leader.")
		group.leader_id = self_id

		start_heartbeat()
		start_overseer()

		broadcast_new_leader()
		# push_messages_to_peers()
	elif not new_nds_group:
		logging.info("NDS has deleted the group already.")
		# Group does not exist
		set_active_group(None)
		networking.refresh_group(None)
	else:
		# Old leader still exists
		current_leader_ip = new_nds_group.leader_ip
		logging.info(
			f"Some leader already exists, with ip {current_leader_ip}, requesting to join group."
		)

		new_group = request_to_join_group(current_leader_ip)

		logging.info(f"Gropu joined {new_group}")

		set_active_group(new_group)
		networking.refresh_group(new_group)

		# after joining new group
		# synchronize_with_leader()

	# If NDS does not exist, we should remove the entire block...


def update_nds_server():
	group = get_active_group()
	group_id = group.group_id
	nds_ip = group.nds_ip
	server = nds_servers[nds_ip]
	if server:
		remote_server = server.get_proxy()
		response: UpdateGroupResponse = UpdateGroupResponse.from_json(
			remote_server.update_group_leader(group_id)
		)
		return (response.ok, response.group)
	else:
		logging.error("NDS server not found.")
		return (False, None)


@dispatcher.public
def still_leader_of_group(group_id):
	group = get_active_group()
	if group and group.group_id == group_id and group.leader_id == group.self_id:
		return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


def broadcast_new_leader():
	group = get_active_group()
	peers = group.peers
	self_id = group.self_id

	peers_to_remove = []
	for peer_id, peer_info in peers.items():
		if peer_id == self_id:
			continue
		peer_ip = peer_info.ip
		try:
			rpc_client = create_rpc_client(peer_ip, node_port)
			remote_server = rpc_client.get_proxy()
			response: Response = Response.from_json(
				remote_server.update_leader(group.group_id, self_id)
			)
			if not response.ok:
				peers_to_remove.append(peer_id)
				logging.info(
					f"Peer {peer_id} no longer in group, removing them from group."
				)
		except Exception:
			peers_to_remove.append(peer_id)
			logging.info(f"Peer {peer_id} not reached, removing them from group.")
			continue

	for peer_id in peers_to_remove:
		group.peers.pop(peer_id)


@dispatcher.public
def update_leader(group_id, new_leader_id):
	group = get_active_group()
	if group and group.group_id == group_id:
		group.leader_id = new_leader_id
		return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


### INTEGRATE BELOW


def store_message(msg, msg_id, group_id, source_id, vector_clock):
	"""Store a message locally."""
	if group_id not in message_store:
		message_store[group_id] = []
	messages = message_store[group_id]
	messages.append(
		{
			"msg_id": msg_id,
			"source_id": source_id,
			"msg": msg,
			"vector_clock": vector_clock,
		}
	)
	message_store[group_id] = messages


def push_messages_to_peers():
	group = get_active_group()
	peers = group.peers
	all_messages = message_store.get(group.group_id, [])
	for peer_id, _ in peers.items():
		push_messages_to_peer(
			group_id=group.group_id, all_messages=all_messages, peer_id=peer_id
		)


@dispatcher.public
def call_for_synchronization(group_id, peer_vector_clock):
	group = get_active_group()
	if group_id == group.group_id:
		all_messages = message_store.get(group_id, [])
		missing_messages = [
			msg for msg in all_messages if msg["vector_clock"] > peer_vector_clock
		]
		return Response(
			ok=True,
			message="Missing messages provided.",
			data={"missing_messages": missing_messages},
		).to_json()


# Used on startup, when node joins it can synchronize its messages with leader.
def synchronize_with_leader():
	group = get_active_group()
	peers = group.peers
	leader_id = group.leader_id
	leader_ip = peers.get(leader_id, {}).get("ip")
	if leader_ip:
		rpc_client = create_rpc_client(leader_ip, node_port)
		remote_server = rpc_client.get_proxy()
		response: Response = Response.from_json(
			remote_server.call_for_synchronization(group.group_id, group.vector_clock)
		)
		if response.ok:
			missing_messages = response.data.get("missing_messages", [])
			if missing_messages:
				update_messages(group.group_id, missing_messages)


## If candidate becomes a leader, it will check all peer messages and updates them based on vector clock.
def push_messages_to_peer(all_messages, peer_id):
	group = get_active_group()
	self_id = group.self_id
	if peer_id == self_id:
		return False

	peer_ip = group.peers.peer_id.ip
	rpc_client = create_rpc_client(peer_ip, node_port)

	remote_server = rpc_client.get_proxy()
	response: Response = Response.from_json(
		remote_server.report_vector_clock(group.group_id)
	)

	if response.ok:
		peer_vector_clock = response.data["vector_clock"]
		missing_messages = [
			msg for msg in all_messages if msg["vector_clock"] > peer_vector_clock
		]
		if missing_messages:
			remote_server.update_messages(group.group_id, missing_messages)
			logging.info(f"Sent {len(missing_messages)} messages to peer {peer_id}")
	else:
		logging.warning(f"Could not fetch vector clock from peer {peer_id}")


@dispatcher.public
def report_vector_clock(group_id):
	group = get_active_group()
	if group_id == group.group_id:
		vector_clock = group.get("vector_clock", 0)
		return Response(
			ok=True,
			message="vector clock reported succesfully.",
			data={"vector_clock": vector_clock},
		).to_json()


@dispatcher.public
def update_messages(group_id, messages):
	group = get_active_group()
	if group_id == group.group_id:
		for msg_data in messages:
			msg_id = msg_data["msg_id"]
			source_id = msg_data["source_id"]
			msg = msg_data["msg"]
			vector_clock = msg_data["vector_clock"]
			if msg_id not in received_messages:
				store_message(msg, msg_id, group_id, source_id, vector_clock)
				received_messages.add(msg_id)
				peers = group.peers
				peer_info = peers.get(source_id)
				peer_name = peer_info.get("name", "Unknown")
				networking.receive_messages(
					source_name=peer_name, msg=(vector_clock, msg)
				)
		if messages:
			max_vector_clock = max(msg["vector_clock"] for msg in messages)
			group.vector_clock = max(group.get("vector_clock", 0), max_vector_clock)
		return Response(
			ok=True, message="messages have been received successfully."
		).to_json()
	return Response(
		ok=False, message="messages were not received successfully."
	).to_json()


if __name__ == "__main__":
	serve()
