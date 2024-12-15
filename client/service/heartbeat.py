### HEARTBEAT
# thread that sends rpc to leader or NDS every now and then
import random
import logging
import threading
import time


from client.structs.client import HeartbeatResponse
from client.structs.nds import NDS_HeartbeatResponse


def start_heartbeat(app):
	if app.heartbeat:
		# Kill existing heartbeat
		logging.info(f"Killing heartbeat {app.heartbeat_counter}")
		app.heartbeat_kill_flags.add(app.heartbeat_counter)

	logging.info("Starting heartbeat sending.")
	app.heartbeat_counter += 1
	app.heartbeat = threading.Thread(target=heartbeat_thread, args=(app,), daemon=True)
	app.heartbeat.start()


def heartbeat_thread(app):
	# Wrap in try clause, so that can be closed with .raise_exception()
	try:
		while True:
			logging.info(f"HB: Sending heartbeat at {app.heartbeat_counter}.")
			if app.heartbeat_counter in app.heartbeat_kill_flags:
				raise InterruptedError

			if not app.active_group:
				logging.info("HB: Group not found, interrupted")
				raise InterruptedError

			# If this node NOT leader, send heartbeat to leader
			if app.active_group.self_id != app.active_group.leader_id:
				send_heartbeat_to_leader(app)
			else:
				send_heartbeat_to_nds(app)

			# Sleep for a random interval, balances out leader election more
			interval = random.uniform(
				app.heartbeat_min_interval, app.heartbeat_max_interval
			)
			time.sleep(interval)
	finally:
		logging.info(f"HB: Killing heartbeat {app.heartbeat_counter}.")


def send_heartbeat_to_leader(app):
	leader = app.active_group.peers.get(app.active_group.leader_id)
	if not leader:
		logging.error("HB: Leader not found, initiating election...")
		app.leader_election(app, app.active_group.group_id)
		return None

	try:
		leader_ip = leader.ip
		client = app.create_rpc_client(leader_ip, app.node_port).get_proxy()
		logging.info(
			f"HB: Sending heartbeat to leader from Peer ID {app.active_group.self_id}."
		)
		response: HeartbeatResponse = HeartbeatResponse.from_json(
			client.receive_heartbeat(
				app.active_group.self_id, app.active_group.group_id
			)
		)
		if response.ok:
			logging.info("HB: Refreshing peers.")
			app.active_group.peers = response.peers
			app.networking.refresh_group(app.active_group)
		elif response.message == "changed-group":
			logging.warning("HB: Leader changed group.")
			app.leader_election(app, app.active_group.group_id)
		else:
			logging.warning("HB: Leader said not ok: we got kicked!")
			app.active_group = None
			app.networking.refresh_group(app.active_group)
	except Exception as e:
		logging.error(f"EXC: HB: Error sending heartbeat to leader: {e}")
		app.leader_election(app, app.active_group.group_id)


def send_heartbeat_to_nds(app):
	# This node is leader, send heartbeat to NDS
	remote_server = app.nds_servers[app.active_group.nds_ip]
	remote_server.get_proxy()
	if not remote_server:
		logging.error("HB: NDS server not found.")
		return False

	try:
		logging.info("HB: Sending heartbeat to NDS.")
		response: NDS_HeartbeatResponse = NDS_HeartbeatResponse.from_json(
			remote_server.receive_heartbeat(app.active_group.group_id)
		)
		logging.info(f"HB: NDS message: {response.message}")
		if response.ok:
			logging.info("HB: NDS beats for heartbeat.")
			return True

		if response.message == "group-deleted-womp-womp":
			logging.error("HB: NDS deleted the group :(")
			app.active_group = None
			app.networking.refresh_group(app.active_group)
		else:
			logging.error("HB: NDS rejected heartbeat.")

	except BaseException as e:
		logging.error(f"EXC: HB: Failed to send heartbeat to NDS: {e}")
