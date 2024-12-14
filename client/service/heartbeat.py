### HEARTBEAT
# thread that sends rpc to leader or NDS every now and then
import random
import logging
import threading
import time


from structs.client import HeartbeatResponse
from structs.nds import NDS_HeartbeatResponse


def start_heartbeat(app):
	if app.heartbeat:
		# Kill existing heartbeat
		logging.info(f"Killing heartbeat {app.heartbeat_counter}")
		heartbeat_kill_flags.add(app.heartbeat_counter)

	logging.info("Starting heartbeat sending.")
	app.heartbeat_counter += 1
	heartbeat = threading.Thread(
		target=heartbeat_thread, args=(app, app.heartbeat_counter,), daemon=True
	)
	heartbeat.start()


def heartbeat_thread(app, hb_id: int):
	global heartbeat_kill_flags
	# Wrap in try clause, so that can be closed with .raise_exception()
	try:
		while True:
			logging.info(f"HB: Sending heartbeat at {hb_id}.")
			if hb_id in heartbeat_kill_flags:
				raise InterruptedError

			group = app.active_group
			if not group:
				raise InterruptedError

			# If this node NOT leader, send heartbeat to leader
			if group.self_id != group.leader_id:
				send_heartbeat_to_leader(app)
			else:
				send_heartbeat_to_nds(app)

			# Sleep for a random interval, balances out leader election more
			interval = random.uniform(app.heartbeat_min_interval, app.heartbeat_max_interval)
			time.sleep(interval)
	finally:
		logging.info(f"HB: Killing heartbeat {hb_id}.")


def send_heartbeat_to_leader(app):
	active = app.active_group
	leader_ip = active.peers[active.leader_id].ip
	if not leader_ip:
		logging.error("HB: Leader IP not found, initiating election...")
		app.leader_election(app, active.group_id)
		return

	try:
		leader = app.create_rpc_client(leader_ip, app.node_port).get_proxy()
		logging.info(f"HB: Sending heartbeat to leader from {active.self_id}.")
		response: HeartbeatResponse = HeartbeatResponse.from_json(
			leader.receive_heartbeat(active.self_id, active.group_id)
		)
		if response.ok:
			logging.info("HB: Refreshing peers.")
			active.peers = response.peers
			app.networking.refresh_group(active)
		elif response.message == "changed-group":
			logging.warning("HB: Leader changed group.")
			app.leader_election(app, active.group_id)
		else:
			# response.message == "you-got-kicked-lol"
			logging.warning("HB: Leader said not ok, we got kicked!")
			app.active_group = None
			app.networking.refresh_group(None)
	except Exception as e:
		logging.error(f"EXC: HB: Error sending hearbeat to leader: {e}")
		app.leader_election(app, active.group_id)


def send_heartbeat_to_nds(app):
	active = app.active_group
	# This node is leader, send heartbeat to NDS
	remote_server = app.nds_servers[active.nds_ip].get_proxy()
	if not remote_server:
		logging.error("HB: NDS server not found.")

	try:
		logging.info("HB: Sending heartbeat to NDS.")
		response: NDS_HeartbeatResponse = NDS_HeartbeatResponse.from_json(
			remote_server.receive_heartbeat(active.group_id)
		)
		if not response.ok:
			if response.message == "group-deleted-womp-womp":
				logging.error("HB: NDS deleted the group :(")
				app.active_group = None
				app.networking.refresh_group(None)
			else:
				logging.error("HB: NDS rejected heartbeat?")
	except BaseException as e:
		logging.error(f"EXC: HB: Failed to send heartbeat to NDS: {e}")
