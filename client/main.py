import grpc
import shelve
import random
from concurrent import futures

from protos import health_pb2, health_pb2_grpc
from protos import network_pb2, network_pb2_grpc
from protos import peer_pb2, peer_pb2_grpc

from ui import run

class PeerService(peer_pb2_grpc.PeerServiceServicer):
    def __init__(self, ip, nds_ip, channel_port=50051):
        self.ip = ip
        self.nds_ip = nds_ip
        self.is_leader = {}
        self.channel_port = channel_port
        self.networks = {} # A dict of chats, { chat_id: {peer_id, leader_ip, peers={id: ip}}}
        self.peers = {}
        self.message_store = shelve.open(f"{self.ip}_messages.db", writeback=True)
        self.received_messages = set()

    def store_message(self, chat_id, msg_id, source_id, msg):
            """Store a message locally."""
            if chat_id not in self.message_store:
                self.message_store[chat_id] = []
            self.message_store[chat_id].append({
                "msg_id": msg_id,
                "source_id": source_id,
                "msg": msg
            })
            self.message_store.sync() 
    
    def get_messages(self, chat_id):
        """Retrieve all messages for a given chat_id."""
        messages = self.message_store.get(chat_id, [])
        return messages

    def stub_fetch_networks(self):
        """Returns possible networks to join"""
        with grpc.insecure_channel(self.nds_ip) as channel:
            stub = network_pb2_grpc.NetworkServiceStub(channel)
            response = stub.GetNetworks(network_pb2.GetNetworksRequest())
            return response.networks
    
    def stub_join_network(self, leader_ip, chat_id):
        with grpc.insecure_channel(leader_ip) as channel:
            stub = peer_pb2_grpc.PeerServiceStub(channel)
            response = stub.JoinNetwork(peer_pb2.JoinNetworkRequest(peer_ip=leader_ip, chat_id=chat_id))
            if response.success:
                self.networks[chat_id] = {
                    "peer_id": response.assigned_peer_id,
                    "leader_ip": response.leader_ip,
                    "peers": {peer.id: peer.ip for peer in response.peers}
                }
                print(f"Joined network with Peer ID: {response.assigned_peer_id}")
            else:
                print("Failed to join network")

    def stub_create_network(self, chat_name):
        """Create a new network and register it with NDS, making this peer the leader."""
        with grpc.insecure_channel(self.nds_ip) as channel:
            stub = network_pb2_grpc.NetworkServiceStub(channel)
            response = stub.CreateNetwork(network_pb2.CreateNetworkRequest(
                leader_ip=self.ip, chat_name=chat_name
            ))
            if response.success:
                chat_id = response.chat_id
                self.networks[chat_id] = {
                    "leader_ip": self.ip,
                    "peer_id": 0,
                    "peers": {},
                }

                self.is_leader[chat_id] = True
                self.leader_ip = self.ip
                print(f"Created network {chat_name} with ID: {response.chat_id}")
            else: 
                print(f"Failed to create network {chat_name}")

    def JoinNetwork(self, request, context):
        chat_id = request.chat_id
        if not self.is_leader.get(chat_id, False):
            return peer_pb2.JoinNetworkResponse(
                success=False,
                message="Only the leader can add peers"
            )
        
        network = self.networks[chat_id]
        peer_id = max(network["peers"].keys(), default=0) + 1
        self.peers[peer_id] = request.peer_ip
        network["peers"][peer_id] = request.peer_ip
        print(f"Peer {self.peer_id} joined with IP {request.peer_ip}")
        return peer_pb2.JoinNetworkResponse(
            success=True, 
            message="Joined successfully", 
            assigned_peer_id=peer_id, 
            leader_ip=network["leader_ip"],
            peers=[peer_pb2.PeerInfo(ip=ip, id=id) for id, ip in network["peers"].items()]
        )
    
    def LeaveNetwork(self, request, context):
        """Handles leaving the network"""
        chat_id = request.chat_id
        if not self.is_leader.get(chat_id, False):
            return peer_pb2.LeaveNetworkResponse(
                success=False,
                message="Only leader can remove peers"
            )
        
        network = self.networks.get(chat_id)
        peer_id = request.peer_id
        if network and peer_id in network["peers"]:
            del self.peers[peer_id]
            print(f"Peer {peer_id} left the network")
            return peer_pb2.LeaveNetworkResponse(success=True, message="Left network successfully")
        return peer_pb2.LeaveNetworkResponse(success=False, message="Peer not found")
    
    def SendMessage(self, request, context):
        """Broadcast a message to all peers using flooding."""
        chat_id = request.chat_id
        msg_id = request.msg_id
        source_id = request.source_id
        destination_id = request.destination_id
        msg = request.msg

        if destination_id == -1:  
            print(f"Broadcasting message {msg_id} from {source_id}: {msg}")
            self.flood_message_randomly(chat_id, msg_id, source_id, msg)
            return peer_pb2.MessageResponse(success=True, message="Message broadcasted")
        else:
            destination_ip = self.peers.get(destination_id)
            if destination_ip:
                self.send_message_to_peer(destination_ip, chat_id, msg_id, source_id, msg)
                return peer_pb2.MessageResponse(success=True, message="Message sent")
            else:
                return peer_pb2.MessageResponse(success=False, message="Destination peer not found")

    def flood_message_randomly(self, chat_id, msg_id, source_id, msg):
        """Flood a message to all peers."""
        network = self.networks.get(chat_id)
        if not network:
            print(f"No network found for chat_id {chat_id}.")
            return

        peer_ids = [peer_id for peer_id in network["peers"] if peer_id != source_id]
        if not peer_ids:
            print("No peers available to forward the message.")
            return
    
        num_peers_to_forward = max(1, len(peer_ids) // 2) 
        selected_peers = random.sample(peer_ids, num_peers_to_forward)

        for peer_id in selected_peers:
                peer_ip = network["peers"][peer_id]
                self.send_message_to_peer(peer_ip, chat_id, msg_id, source_id, msg)

    def send_message_to_peer(self, peer_ip, chat_id, msg_id, source_id, msg):
        with grpc.insecure_channel(f"{peer_ip}:{self.channel_port}") as channel:
            stub = peer_pb2_grpc.PeerServiceStub(channel)
            message_request = peer_pb2.MessageRequest(
                chat_id=chat_id,
                msg_id=msg_id,
                source_id=source_id,
                destination_id=-1,
                msg=msg
            )

            try:
                response = stub.ReceiveMessage(message_request)
                print(f"Message sent to {peer_ip}, response: {response.message}")
            except grpc.RpcError as e:
                print(f"Failed to send message to {peer_ip}: {e}")

    def ReceiveMessage(self, request, context):
        """Handle receiving a broadcasted message."""
        chat_id = request.chat_id
        msg_id = request.msg_id
        source_id = request.source_id
        msg = request.msg
        if msg_id in self.received_messages:
            return peer_pb2.MessageResponse(success=True, message="Duplicate message")

        self.received_messages.add(msg_id)
        self.store_message(chat_id, msg_id, request.source_id, request.msg)

        if request.destination_id == -1:
            self.flood_message_randomly(chat_id, msg_id, source_id, msg)

        return peer_pb2.MessageResponse(success=True, message="Message received")
    
    def LivenessPing(self, request, context):
        """Respond to a liveness check."""
        return peer_pb2.LivenessPingResponse(success=True)

def serve(ip, nds_ip, port):
	server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
	health_pb2_grpc.add_HealthServicer_to_server(HealthServicer(), server)
	network_pb2_grpc.add_NetworkServiceServicer_to_server(NetworkService(), server)
    
	peer_service = PeerService(ip, nds_ip, channel_port)
	peer_pb2_grpc.add_PeerServiceServicer_to_server(peer_service, server)
	server.add_insecure_port(f'[::]:{port}')
	server.start()
	print(f"Server is running on {ip}:{port}")
	server.wait_for_termination()

if __name__ == "__main__":
	# serve(ip="127.0.0.1", nds_ip="127.0.0.1", port=50051)
	run()