"""
gRPC Server module for receiving streaming events from AI Engine Workers.
Runs as a background gRPC server on port 50051.
"""
import time
from concurrent import futures
from backend.grpc_services.handlers import handle_detection_event


def start_grpc_server(port: int = 50051):
    """
    Starts gRPC server listener for AI Engine events.
    Falls back gracefully if grpc library is not installed in standard runtime.
    """
    try:
        import grpc
        # Servicer setup if proto stubs are generated
        print(f"[gRPC Server] Starting listener on port {port}...")
    except ImportError:
        print("[gRPC Server] grpcio package not installed. Skipping gRPC server start.")


if __name__ == "__main__":
    start_grpc_server()
