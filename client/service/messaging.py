### MESSAGING
import logging
from structs.client import ReceiveMessageResponse


def message_broadcast(app, msg, msg_id, group_id, source_id) -> bool:
	"""Broadcast a message as leader to other peers

	Args:
		msg (str): A message that user want to send.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
		source_id (str): Peer ID where the message came from.

	Returns:
		bool: If message was sent successfully.
	"""
	group = app.active_group
	peers = list(group.peers.values())
	target_peers = []

	for p in peers:
		if p.node_id != source_id and p.node_id != group.self_id:
			target_peers.append(p)

	if not target_peers:
		logging.info(f"No other peers found for group {group_id}.")
		return False

	app.logical_clock = app.logical_clock + 1
	logging.info(f"Broadcasting message to peers: {peers}")
	for peer in target_peers:
		send_message_to_peer(
			app, peer.ip, msg, msg_id, group_id, source_id, app.logical_clock
		)
	return True


def send_message_to_peer(
	app, client_ip, msg, msg_id, group_id, source_id, logical_clock
):
	"""Send a message to individual targeted peer.

	Args:
		client (object): The rpc_client to the peer.
		msg (str): the message.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
	"""
	try:
		remote_server = app.create_rpc_client(client_ip, app.node_port)
		response: ReceiveMessageResponse = ReceiveMessageResponse.from_json(
			remote_server.receive_message(
				msg=msg,
				msg_id=msg_id,
				group_id=group_id,
				source_id=source_id,
				leader_logical_clock=logical_clock,
			)
		)
		if response.ok:
			logging.info("Leader received message successfully.")
			return True
		if not response.ok:
			logging.info(f"Failed to send message: {response.message}")
			return False
	except BaseException as e:
		logging.info(f"Failed to send message: {e}")
		return False
