import logging
from .overseer import start_overseer
from .synchronization import (
	synchronize_messages_with_peers,
	synchronize_with_leader,
)
from client.structs.client import UpdateGroupResponse
from client.structs.generic import Response


### LEADER ELECTION
def leader_election(app, group_id):
	logging.info("Starting leader election.")
	active_group = app.active_group
	peers = active_group.peers
	self_id = active_group.self_id

	low_id_nodes = [peer_id for peer_id in peers if peer_id < self_id]
	got_answer = None
	if not low_id_nodes:
		logging.info("No other nodes found, making self leader.")
		become_leader(app)
		return

	for peer_id in low_id_nodes:
		peer = peers[peer_id]
		peer_ip = peer.ip

		logging.info(f"Pinging {peer_id} if they want to be leader...")
		try:
			remote_server = app.create_rpc_client(peer_ip, app.node_port)
			response: Response = Response.from_json(
				remote_server.election_message(group_id, self_id)
			)
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
		become_leader(app)


def become_leader(app):
	self_id = app.active_group.self_id

	logging.info("Pinging NDS that we want to be leader.")
	did_update, new_nds_group = update_nds_server(app)

	if did_update and new_nds_group:
		logging.info("NDS made us leader.")
		app.active_group.leader_id = self_id
		start_overseer(app)
		broadcast_new_leader(app)
		synchronize_messages_with_peers(app)

	elif not new_nds_group:
		logging.info("NDS has deleted the group already. Creating the group.")
		new_group = app.create_group(app.active_group.group_name, app.active_group.nds_ip)
		app.active_group = new_group
		app.networking.refresh_group(app.active_group)

	else:
		current_leader_ip = new_nds_group.leader_ip
		logging.info(
			f"Some leader already exists, with ip {current_leader_ip}, requesting to join group."
		)
		new_group = app.request_to_join_group(current_leader_ip, new_nds_group.group_id)
		logging.info(f"Group joined {new_group}")
		app.active_group = new_group
		app.networking.refresh_group(app.active_group)
		synchronize_with_leader(app)


def update_nds_server(app):
	group_id = app.active_group.group_id
	nds_ip = app.active_group.nds_ip
	remote_server = app.nds_servers[nds_ip]

	if remote_server:
		response: UpdateGroupResponse = UpdateGroupResponse.from_json(
			remote_server.update_group_leader(group_id)
		)
		return (response.ok, response.group)

	else:
		logging.error("NDS server not found.")
		return (False, None)


def broadcast_new_leader(app):
	peers = app.active_group.peers
	self_id = app.active_group.self_id

	peers_to_remove = []
	for peer_id, peer_info in peers.items():
		if peer_id == self_id:
			continue
		peer_ip = peer_info.ip

		try:
			remote_server = app.create_rpc_client(peer_ip, app.node_port)
			response: Response = Response.from_json(
				remote_server.update_leader(app.active_group.group_id, self_id)
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
		app.active_group.peers.peers.pop(peer_id)
