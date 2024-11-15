import grpc
from concurrent import futures
import socket
import uuid

from protos import health_pb2, health_pb2_grpc
from protos import network_pb2, network_pb2_grpc

class HealthServicer(health_pb2_grpc.HealthServicer):
	def Ping(self, request, context):
		return health_pb2.HealthResponse(message=f"Hello, {request.name}")

class NetworkService(network_pb2_grpc.NetworkServiceServicer):
	def __init__(self):
		self.networks = {}
	
	def CreateNetwork(self, request, context):
		"""Create a new chat."""
		chat_id = str(uuid.uuid4())

		if request.chat_id not in self.networks:
			self.networks[request.chat_id] = {
				"leader_ip": request.leader_ip,
				"chat_id": chat_id,
				"chat_name": request.chat_name
			}
			return network_pb2.CreateNetworkResponse(success=True, chat_id=chat_id, message="Chat created successfully")
		else:
			return network_pb2.CreateNetworkResponse(success=False, chat_id="", message=f"Error: Chat with the id '{request.chat_id}' already exists.")

	def GetNetworks(self, request, context):
		"""Get all possible chats to join."""
		networks_list = []
		for network in self.networks.values():
			network_info = network_pb2.NetworkInfo(
				leader_ip=network["leader_ip"],
				chat_id=network["chat_id"],
				chat_name=network["chat_name"]
			)
			network_list.append(network_info)
		return network_pb2.GetNetworksResponse(networks=networks_list)
	
	def UpdateNetworkLeader(self, request, context):
		"""Updates a leader of a network after leader election."""
		chat_id = request.chat_id
		new_leader_ip = request.new_leader_ip

		if chat_id not in self.networks:
			return network_pb2.UpdateNetworkLeaderResponse(success=False, message="Chat not found.")
		
		current_leader = self.networks[chat_id]["leader_ip"]
		if current_leader and self.Liveness(current_leader):
			return network_pb2.UpdateNetworkLeaderResponse(success=False, message="Leader is alive.")
		
		self.networks[chat_id]["leader_ip"] = new_leader_ip
		return network_pb2.UpdateNetworkLeaderResponse(success=True, message="Leader has been updated successfully.")
	
	def Liveness(self, ip):
		"""Liveness check that a node is alive."""
		try:
			with socket.create_connection((ip, 50051), timeout=2):
				return True
		except (socket.timeout, socket.error):
			return False

def serve():
	server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
	health_pb2_grpc.add_HealthServicer_to_server(HealthServicer(), server)
	network_pb2_grpc.add_NetworkServiceServicer_to_server(NetworkService(), server)
	server.add_insecure_port('[::]:50051')
	server.start()
	print("Server is running on port 50051")
	server.wait_for_termination()

def main():
	serve()

if __name__ == "__main__":
	main()
