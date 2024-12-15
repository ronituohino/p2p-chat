### OVERSEEING
# thread that checks which nodes have sent heartbeat to me (leader) every now and then
import logging
import threading
import time


def start_overseer(app):
	"""Starts overseeing thread"""
	if app.overseer:
		# Kill existing heartbeat
		logging.info(f"Killing overseer {app.overseer_counter}.")
		app.heartbeat_kill_flags.discard(app.heartbeat_counter)
		app.overseer_kill_flags.add(app.overseer_counter)

	logging.info("Starting overseer.")
	app.overseer_counter += 1
	app.overseer = threading.Thread(
		target=overseer_thread, args=(app, app.overseer_counter), daemon=True
	)
	app.overseer.start()


def overseer_thread(app, ov_id: int):
	"""Thread to monitor heartbeats from followers, deleting ones not active"""
	try:
		previous_state = set(app.active_group.peers.keys())
		while True:
			logging.info(f"OV: Overseeing at {ov_id}.")
			if ov_id in app.overseer_kill_flags:
				logging.info(f"OV: Overseer {ov_id} stopped intentionally.")
				raise InterruptedError

			if (
				not app.active_group
				or app.active_group.self_id != app.active_group.leader_id
			):
				logging.warning(
					"OV: Active group is missing or node is not leader. Stopping overseer."
				)
				raise InterruptedError

			logging.info(
				f"OV: last node responses: {app.last_node_response} and peers: {app.active_group.peers}"
			)
			with app.overseer_lock:
				if not app.last_node_response:
					app.last_node_response = {
						node_id: 0 for node_id in app.active_group.peers.keys()
					}
					logging.info(
						f"Current last_node_response state: {app.last_node_response}"
					)
				logging.info(f"OV: overseer {ov_id} acquired lock")

				nodes_to_delete = []
				for node_id in app.last_node_response.keys():
					logging.info(
						f"OV: node {node_id} has following node response count {app.last_node_response[node_id]}"
					)
					if node_id not in app.last_node_response:
						app.last_node_response[node_id] = 0

					if node_id == app.active_group.self_id:
						app.last_node_response[node_id] = 0
						continue

					app.last_node_response[node_id] += 1
					if app.last_node_response[node_id] > app.overseer_cycles_timeout:
						# If have not received heartbeat from group leader in x cycles, delete Group
						logging.info(f"Removing a node with node ID: {node_id}")
						nodes_to_delete.append(node_id)

				for node_id in nodes_to_delete:
					del app.last_node_response[node_id]
					del app.active_group.peers[node_id]
					logging.info(
						f"OV: Node {node_id} deleted -- no heartbeat from node."
					)
				
			updated_state = set(app.active_group.peers.keys())
			added_peers = updated_state - previous_state
			removed_peers = previous_state - updated_state

			if added_peers or removed_peers:
				logging.info(
					f"OV: State change, Added {added_peers}, Removed {removed_peers}"
				)
				app.networking.refresh_group(app.active_group)

			previous_state = updated_state
			time.sleep(app.overseer_interval)
	except Exception as e:
		logging.error(f"EXC: Critical error, Overseer failed {e}")
	finally:
		logging.info(f"OV: Overseer {ov_id} killed.")
