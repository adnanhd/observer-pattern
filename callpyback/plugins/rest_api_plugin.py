"""
REST API plugin for CallPyBack message queue system.
Provides HTTP endpoints for pub-sub operations and task management.
"""

import asyncio
import json
import threading
import time
from typing import Any, Dict, List, Optional, Union

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from callpyback import CallPyBack
from callpyback.plugins.core.message_queue import MessageQueue, Message


# Pydantic models for API
if HAS_FASTAPI:
    class PublishRequest(BaseModel):
        topic: str = Field(..., description="Topic to publish to")
        payload: Any = Field(..., description="Message payload")
        headers: Optional[Dict[str, Any]] = Field(None, description="Optional headers")
        sender: Optional[str] = Field(None, description="Sender identifier")
        reply_to: Optional[str] = Field(None, description="Reply-to topic")

    class SubscribeRequest(BaseModel):
        topic: str = Field(..., description="Topic to subscribe to")
        webhook_url: Optional[str] = Field(None, description="Webhook URL for notifications")
        filters: Optional[Dict[str, Any]] = Field(None, description="Message filters")
        max_retries: int = Field(3, description="Maximum retry attempts")

    class TaskSubmissionRequest(BaseModel):
        function_name: str = Field(..., description="Function to execute")
        args: List[Any] = Field(default_factory=list, description="Function arguments")
        kwargs: Dict[str, Any] = Field(default_factory=dict, description="Function keyword arguments")
        priority: int = Field(0, description="Task priority")
        timeout: Optional[float] = Field(None, description="Task timeout")
        strategy: Optional[str] = Field(None, description="Execution strategy (thread/process)")

    class MessageResponse(BaseModel):
        id: str
        topic: str
        payload: Any
        headers: Dict[str, Any]
        timestamp: float
        sender: Optional[str]
        reply_to: Optional[str]

    class TaskResponse(BaseModel):
        task_id: str
        status: str
        result: Optional[Any] = None
        error: Optional[str] = None
        execution_time: Optional[float] = None


class WebhookHandler:
    """Handles webhook notifications for subscriptions."""
    
    def __init__(self):
        self.webhooks: Dict[str, str] = {}  # subscription_id -> webhook_url
        self.session = None
        self.lock = threading.RLock()
    
    async def add_webhook(self, subscription_id: str, webhook_url: str):
        """Add webhook for subscription."""
        with self.lock:
            self.webhooks[subscription_id] = webhook_url
    
    async def remove_webhook(self, subscription_id: str):
        """Remove webhook for subscription."""
        with self.lock:
            self.webhooks.pop(subscription_id, None)
    
    async def notify_webhook(self, subscription_id: str, message: Message):
        """Send notification to webhook."""
        webhook_url = self.webhooks.get(subscription_id)
        if not webhook_url:
            return
        
        try:
            import aiohttp
            
            payload = {
                'id': message.id,
                'topic': message.topic,
                'payload': message.payload,
                'headers': message.headers,
                'timestamp': message.timestamp,
                'sender': message.sender,
                'reply_to': message.reply_to
            }
            
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            async with self.session.post(webhook_url, json=payload) as response:
                if response.status >= 400:
                    print(f"Webhook notification failed: {response.status}")
        
        except Exception as e:
            print(f"Webhook error: {e}")


class RESTAPIPlugin:
    """
    REST API plugin for CallPyBack message queue system.
    
    Provides HTTP endpoints for:
    - Publishing messages
    - Managing subscriptions
    - Task submission and monitoring
    - Queue statistics and monitoring
    - WebSocket support for real-time updates
    """
    
    def __init__(self,
                 message_queue: MessageQueue,
                 executor: Optional[Any] = None,
                 host: str = "0.0.0.0",
                 port: int = 8000,
                 enable_cors: bool = True,
                 enable_websockets: bool = True):
        """
        Initialize REST API plugin.
        
        Args:
            message_queue: MessageQueue instance
            executor: Task executor (ThreadExecutor, ProcessExecutor, or HybridExecutor)
            host: Server host
            port: Server port
            enable_cors: Enable CORS middleware
            enable_websockets: Enable WebSocket support
        """
        if not HAS_FASTAPI:
            raise ImportError("FastAPI is required for REST API plugin. Install with: pip install fastapi uvicorn")
        
        self.message_queue = message_queue
        self.executor = executor
        self.host = host
        self.port = port
        self.enable_cors = enable_cors
        self.enable_websockets = enable_websockets
        
        # FastAPI app
        self.app = FastAPI(
            title="CallPyBack Message Queue API",
            description="REST API for CallPyBack pub-sub system",
            version="1.0.0"
        )
        
        # Webhook handler
        self.webhook_handler = WebhookHandler()
        
        # WebSocket connections
        self.websocket_connections: Dict[str, Any] = {}
        
        # Function registry for remote execution
        self.function_registry: Dict[str, CallPyBack] = {}
        
        # Setup middleware and routes
        self._setup_middleware()
        self._setup_routes()
        
        # Server instance
        self.server = None
        self.server_thread = None
    
    def register_function(self, name: str, func: Union[CallPyBack, callable]):
        """Register function for remote execution."""
        if not isinstance(func, CallPyBack):
            func = CallPyBack()(func)
        self.function_registry[name] = func
    
    def _setup_middleware(self):
        """Setup FastAPI middleware."""
        if self.enable_cors:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
    
    def _setup_routes(self):
        """Setup API routes."""
        
        @self.app.get("/")
        async def root():
            """API root endpoint."""
            return {
                "message": "CallPyBack Message Queue API",
                "version": "1.0.0",
                "endpoints": {
                    "publish": "POST /messages/publish",
                    "subscribe": "POST /subscriptions",
                    "tasks": "POST /tasks",
                    "stats": "GET /stats"
                }
            }
        
        @self.app.post("/messages/publish")
        async def publish_message(request: PublishRequest):
            """Publish message to topic."""
            try:
                message_id = self.message_queue.publish(
                    topic=request.topic,
                    payload=request.payload,
                    headers=request.headers,
                    sender=request.sender,
                    reply_to=request.reply_to
                )
                
                # Notify WebSocket subscribers
                await self._notify_websocket_subscribers(request.topic, {
                    "type": "message",
                    "topic": request.topic,
                    "message_id": message_id,
                    "payload": request.payload
                })
                
                return {"message_id": message_id, "status": "published"}
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.post("/messages/request")
        async def request_response(request: PublishRequest, timeout: float = 10.0):
            """Send request and wait for response."""
            try:
                response = self.message_queue.request(
                    topic=request.topic,
                    payload=request.payload,
                    timeout=timeout,
                    headers=request.headers
                )
                return {"response": response}
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.post("/subscriptions")
        async def create_subscription(request: SubscribeRequest):
            """Create subscription to topic."""
            try:
                # Create callback function
                async def message_handler(message: Message):
                    # Send to webhook if configured
                    if request.webhook_url:
                        await self.webhook_handler.notify_webhook(subscription_id, message)
                    return message.payload
                
                subscription_id = self.message_queue.subscribe(
                    topic=request.topic,
                    callback=message_handler,
                    filters=request.filters,
                    max_retries=request.max_retries
                )
                
                # Setup webhook if provided
                if request.webhook_url:
                    await self.webhook_handler.add_webhook(subscription_id, request.webhook_url)
                
                return {
                    "subscription_id": subscription_id,
                    "topic": request.topic,
                    "status": "subscribed"
                }
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.delete("/subscriptions/{subscription_id}")
        async def remove_subscription(subscription_id: str):
            """Remove subscription."""
            try:
                success = self.message_queue.unsubscribe(subscription_id)
                await self.webhook_handler.remove_webhook(subscription_id)
                
                if success:
                    return {"status": "unsubscribed"}
                else:
                    raise HTTPException(status_code=404, detail="Subscription not found")
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/topics")
        async def list_topics():
            """List active topics."""
            topics = self.message_queue.get_topics()
            return {"topics": topics}
        
        @self.app.post("/tasks")
        async def submit_task(request: TaskSubmissionRequest):
            """Submit task for execution."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Task executor not available")
            
            try:
                # Get function from registry
                if request.function_name not in self.function_registry:
                    raise HTTPException(status_code=404, detail=f"Function '{request.function_name}' not registered")
                
                func = self.function_registry[request.function_name]
                
                # Submit task
                if hasattr(self.executor, 'submit'):
                    task_id = self.executor.submit(
                        func,
                        *request.args,
                        priority=request.priority,
                        timeout=request.timeout,
                        force_strategy=request.strategy,
                        **request.kwargs
                    )
                else:
                    raise HTTPException(status_code=503, detail="Executor does not support task submission")
                
                return {"task_id": task_id, "status": "submitted"}
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/tasks/{task_id}")
        async def get_task_status(task_id: str):
            """Get task status and result."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Task executor not available")
            
            try:
                status = self.executor.get_task_status(task_id)
                
                response = {"task_id": task_id, "status": status}
                
                if status == "completed":
                    try:
                        result = self.executor.get_result(task_id, timeout=0.1)
                        response.update({
                            "result": result.result if result.success else None,
                            "error": str(result.error) if hasattr(result, 'error') and result.error else None,
                            "execution_time": getattr(result, 'execution_time', None)
                        })
                    except:
                        pass
                
                return response
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.delete("/tasks/{task_id}")
        async def cancel_task(task_id: str):
            """Cancel task."""
            if not self.executor:
                raise HTTPException(status_code=503, detail="Task executor not available")
            
            try:
                success = self.executor.cancel_task(task_id)
                return {"task_id": task_id, "cancelled": success}
            
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/stats")
        async def get_stats():
            """Get system statistics."""
            stats = {
                "message_queue": self.message_queue.get_stats(),
                "timestamp": time.time()
            }
            
            if self.executor:
                stats["executor"] = self.executor.get_stats()
            
            return stats
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "message_queue_running": self.message_queue.running,
                "timestamp": time.time()
            }
        
        # WebSocket endpoint
        if self.enable_websockets:
            @self.app.websocket("/ws/{topic}")
            async def websocket_endpoint(websocket, topic: str):
                """WebSocket endpoint for real-time topic updates."""
                await websocket.accept()
                connection_id = str(time.time())
                
                try:
                    # Register connection
                    if topic not in self.websocket_connections:
                        self.websocket_connections[topic] = {}
                    self.websocket_connections[topic][connection_id] = websocket
                    
                    # Keep connection alive and handle messages
                    while True:
                        try:
                            # Wait for messages from client (ping/pong)
                            await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                        except asyncio.TimeoutError:
                            # Send ping to keep connection alive
                            await websocket.send_text(json.dumps({"type": "ping"}))
                        except Exception:
                            break
                
                except Exception as e:
                    print(f"WebSocket error: {e}")
                
                finally:
                    # Clean up connection
                    if topic in self.websocket_connections and connection_id in self.websocket_connections[topic]:
                        del self.websocket_connections[topic][connection_id]
    
    async def _notify_websocket_subscribers(self, topic: str, data: Dict[str, Any]):
        """Notify WebSocket subscribers of a topic."""
        if topic not in self.websocket_connections:
            return
        
        # Send to all connections for this topic
        disconnected = []
        for connection_id, websocket in self.websocket_connections[topic].items():
            try:
                await websocket.send_text(json.dumps(data))
            except Exception:
                disconnected.append(connection_id)
        
        # Clean up disconnected WebSockets
        for connection_id in disconnected:
            del self.websocket_connections[topic][connection_id]
    
    def start(self, background: bool = True):
        """Start the REST API server."""
        if background:
            # Start in background thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name="RESTAPIServer"
            )
            self.server_thread.start()
        else:
            # Start in current thread (blocking)
            self._run_server()
    
    def _run_server(self):
        """Run the FastAPI server."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        self.server = uvicorn.Server(config)
        self.server.run()
    
    def stop(self):
        """Stop the REST API server."""
        if self.server:
            self.server.should_exit = True
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=5.0)
    
    def get_api_docs_url(self) -> str:
        """Get URL for API documentation."""
        return f"http://{self.host}:{self.port}/docs"


# Example usage and testing functions
def create_example_api(message_queue: MessageQueue, executor=None) -> RESTAPIPlugin:
    """Create example API with sample functions."""
    api = RESTAPIPlugin(message_queue, executor)
    
    # Register sample functions
    @CallPyBack()
    def add_numbers(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
    
    @CallPyBack()
    def multiply_numbers(a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b
    
    @CallPyBack()
    def process_data(data: List[int]) -> Dict[str, Any]:
        """Process a list of numbers."""
        return {
            "sum": sum(data),
            "count": len(data),
            "average": sum(data) / len(data) if data else 0,
            "max": max(data) if data else None,
            "min": min(data) if data else None
        }
    
    api.register_function("add", add_numbers)
    api.register_function("multiply", multiply_numbers) 
    api.register_function("process_data", process_data)
    
    return api
