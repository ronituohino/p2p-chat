## Synchronization
import logging
import threading
import time

from client.structs.client import (
	ReportLogicalClockResponse,
	CallForSynchronizationResponse,
	UpdateMessagesResponse,
)


def maintain_received_messages(app):
	"""Thread that periodically removes received messages."""
	while True:
		current_time = time.time()
		with app.received_messages_lock:
			keys_to_remove = [
				msg_id
				for msg_id, timestamp in app.message_timestamps.items()
				if current_time - timestamp > app.MESSAGE_TTL
			]
			for key in keys_to_remove:
				app.received_messages.discard(key)
				del app.message_timestamps[key]
		time.sleep(10)


def store_message(app, msg, msg_id, group_id, source_id, msg_logical_clock):
	"""Store a message locally."""
	group = app.active_group

	if not group:
		logging.error("No active group found.")
		return

	with app.message_store_lock:
		if group_id not in app.message_store:
			app.message_store[group_id] = []

		messages = app.message_store[group_id]

		if msg_id in app.received_messages:
			logging.info(f"Duplicate message {msg_id} ignored.")
			return

		logical_clock = max(app.logical_clock, msg_logical_clock)

		peers = group.peers
		if source_id not in peers:
			logging.warning(f"Source ID {source_id} not found in peers.")
			name = "Unknown (left)"
		else:
			peer = peers[source_id]
			name = peer.name

		messages.append(
			{
				"msg_id": msg_id,
				"source_id": source_id,
				"source_name": name,
				"msg": msg,
				"logical_clock": logical_clock,
			}
		)

		# Limit message capacity to 2000 latest
		max_capacity = 5000
		if len(messages) > max_capacity:
			messages = sorted(
				messages, key=lambda msg: msg["logical_clock"], reverse=True
			)[-max_capacity:]

		app.message_store[group_id] = messages

	logging.info("Message has been stored, refreshing chat")
	if hasattr(app.networking, "refresh_chat"):
		try:
			app.networking.refresh_chat(messages, group.self_id)
			logging.info("Chat has been refreshed")
		except Exception as e:
			logging.error(f"Error refreshing chat_ {e}")
	else:
		logging.warning("Networking does not have a refresh_chat method.")

	with app.received_messages_lock:
		app.received_messages.add(msg_id)


# Used on startup, when node joins it can synchronize its messages with leader.
def synchronize_with_leader(app):
	def sync_thread():
		group = app.active_group
		leader_id = group.leader_id
		leader = group.peers.get(leader_id)
		if not leader:
			logging.warning("Leader not found in peers. Synchronization aborted.")
			return False

		leader_ip = leader.ip
		attempts = 3
		while attempts:
			try:
				remote_server = app.create_rpc_client(leader_ip, app.node_port)
				response: CallForSynchronizationResponse = (
					CallForSynchronizationResponse.from_json(
						remote_server.call_for_synchronization(
							group.group_id, app.logical_clock
						)
					)
				)
				if response.ok:
					missing_messages = response.data.get("missing_messages", [])
					if missing_messages:
						logging.info(
							f"Received {len(missing_messages)} missing messages from leader."
						)
						store_missing_messages(app, group.group_id, missing_messages)
						return True
					else:
						logging.info("No missing messages from leader")

				else:
					logging.warning(f"Synchronization failed: {response.message}")
			except Exception as e:
				logging.error("Error during synchronization with leader", exc_info=True)
				return False
			return True

	thread = threading.Thread(target=sync_thread, daemon=True)
	thread.start()


def store_missing_messages(app, group_id, missing_messages):
	"""Store missing messages and update logical clock for the group"""
	new_messages = []
	logging.info("Storing missing messages.")
	for msg_data in missing_messages:
		msg_id = msg_data["msg_id"]
		if msg_id not in app.received_messages:
			new_messages.append(msg_data)

	# Storing new messages
	for msg_data in new_messages:
		store_message(
			app,
			msg_data["msg"],
			msg_data["msg_id"],
			group_id,
			msg_data["source_id"],
			msg_data["logical_clock"],
		)

	if missing_messages:
		max_logical_clock = max(
			msg_data["logical_clock"] for msg_data in missing_messages
		)
		app.logical_clock = max(app.logical_clock, max_logical_clock)
		logging.info(f"Updated logical clock to {app.logical_clock}")
	else:
		logging.info("No new messages were added.")


## If candidate becomes a leader, it will sync all peer messages and updates them based on logical clock.
def synchronize_messages_with_peers(app):
	group = app.active_group
	if not group:
		logging.warning("No active group to synchronize messages with peers.")
		return

	all_messages = app.message_store[group.group_id]
	for peer in group.peers.values():
		try:
			synchronize_with_peer(app, group, peer, all_messages)
		except Exception as e:
			logging.error(f"Error synchronizing with peer {peer.peer_id}: {str(e)}")


def synchronize_with_peer(app, group, peer, all_messages):
	"""Synchronize messages with a specific peer"""
	peer_id = peer.peer_id
	if peer_id == group.self_id:
		return None

	try:
		remote_server = app.create_rpc_client(peer.ip, app.node_port)
		peer_logical_clock = get_peer_logical_clock(remote_server, group, peer_id)
		if not peer_logical_clock:
			logging.warning(f"Skipping peer {peer.peer_id} due to unreachable clock.")
			return None

		send_missing_messages(
			remote_server, group, all_messages, peer_logical_clock, peer_id
		)
		receive_missing_messages(app, remote_server, group, peer_id)

	except Exception as e:
		logging.error(f"Error synchronizing with peer {peer_id}: {e}")


def get_peer_logical_clock(remote_server, group, peer_id):
	"""Get the logical clock from a peer"""
	try:
		response: ReportLogicalClockResponse = ReportLogicalClockResponse.from_json(
			remote_server.report_logical_clock(group.group_id)
		)

		if not response.ok:
			logging.warning(f"Could not fetch logical clock from peer {peer_id}")
			return None
		return response.data["logical_clock"]
	except Exception as e:
		logging.error(f"Error fetching logical clock from peer {peer_id}: {str(e)}")
		return None


def send_missing_messages(
	remote_server, group, all_messages, peer_logical_clock, peer_id
):
	"""Send messages missing from the peer based on it logical clock"""
	out_missing_messages = [
		msg for msg in all_messages if msg["logical_clock"] > peer_logical_clock
	]

	if not out_missing_messages:
		return

	try:
		if out_missing_messages:
			response: UpdateMessagesResponse = UpdateMessagesResponse.from_json(
				remote_server.update_messages(group.group_id, out_missing_messages)
			)
			if response.ok:
				logging.info(
					f"Sent {len(out_missing_messages)} messages to peer {peer_id}"
				)
			else:
				logging.warning(f"Failed to update messages for peer {peer_id}.")
	except Exception as e:
		logging.error(f"Error sending missing messages to peer {peer_id}: {str(e)}")


def receive_missing_messages(app, remote_server, group, peer_id):
	"""Send messages missing from the peer based on it logical clock"""
	try:
		response: CallForSynchronizationResponse = (
			CallForSynchronizationResponse.from_json(
				remote_server.call_for_synchronization(
					group.group_id, app.logical_clock
				)
			)
		)
		if not response.ok:
			logging.warning(f"Could not synchronize messages with peer {peer_id}.")
			return

		in_missing_messages = response.missing_messages
		if in_missing_messages:
			store_missing_messages(
				app=app, group_id=group.group_id, missing_messages=in_missing_messages
			)
			logging.info(
				f"Received {len(in_missing_messages)} messages from peer {peer_id}."
			)
		else:
			logging.info(f"No new messages received from peer {peer_id}.")
	except Exception as e:
		logging.error(f"Error receiving missing messages from peer {peer_id}: {str(e)}")
