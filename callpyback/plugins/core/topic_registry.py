"""
Topic registry and management for CallPyBack pub-sub system.
Provides centralized topic management and routing.
"""

import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Union

from callpyback import CallPyBack
from callpyback.plugins.core.message_queue import Message, Subscription


@dataclass
class TopicPattern:
    """Topic pattern with wildcard support."""
    
    pattern: str
    regex: Pattern = field(init=False)
    
    def __post_init__(self):
        # Convert topic pattern to regex
        # * matches any sequence except /
        # ** matches any sequence including /
        # ? matches single character
        escaped = re.escape(self.pattern)
        escaped = escaped.replace(r'\*\*', '.*')  # ** becomes .*
        escaped = escaped.replace(r'\*', '[^/]*')  # * becomes [^/]*
        escaped = escaped.replace(r'\?', '.')      # ? becomes .
        self.regex = re.compile(f'^{escaped}$')
    
    def matches(self, topic: str) -> bool:
        """Check if topic matches this pattern."""
        return bool(self.regex.match(topic))


@dataclass
class TopicInfo:
    """Information about a topic."""
    
    name: str
    description: str = ""
    schema: Optional[Dict[str, Any]] = None
    tags: Set[str] = field(default_factory=set)
    created_at: float = field(default_factory=lambda: __import__('time').time())
    subscriber_count: int = 0
    message_count: int = 0
    last_message_at: Optional[float] = None


class TopicRegistry:
    """
    Centralized registry for managing topics and their metadata.
    
    Features:
    - Topic discovery and registration
    - Wildcard pattern matching
    - Topic metadata and schemas
    - Hierarchical topic organization
    - Topic lifecycle management
    """
    
    def __init__(self):
        self.topics: Dict[str, TopicInfo] = {}
        self.patterns: List[TopicPattern] = []
        self.subscribers: Dict[str, List[str]] = defaultdict(list)  # topic -> subscription_ids
        self.subscriptions: Dict[str, Subscription] = {}  # subscription_id -> subscription
        self.lock = threading.RLock()
        
        # Pre-register common patterns
        self.register_pattern("system.**", "System events")
        self.register_pattern("user.*", "User events") 
        self.register_pattern("*.error", "Error events")
        self.register_pattern("*.metrics", "Metrics events")
    
    def register_topic(self, 
                      name: str,
                      description: str = "",
                      schema: Optional[Dict[str, Any]] = None,
                      tags: Optional[Set[str]] = None) -> TopicInfo:
        """
        Register a new topic.
        
        Args:
            name: Topic name
            description: Topic description
            schema: Optional JSON schema for messages
            tags: Topic tags for categorization
            
        Returns:
            TopicInfo instance
        """
        with self.lock:
            if name in self.topics:
                return self.topics[name]
            
            topic_info = TopicInfo(
                name=name,
                description=description,
                schema=schema,
                tags=tags or set()
            )
            
            self.topics[name] = topic_info
            return topic_info
    
    def register_pattern(self, pattern: str, description: str = ""):
        """Register a topic pattern."""
        with self.lock:
            topic_pattern = TopicPattern(pattern)
            self.patterns.append(topic_pattern)
            
            # Register pattern as virtual topic
            self.register_topic(pattern, description, tags={"pattern"})
    
    def find_matching_topics(self, pattern: str) -> List[str]:
        """Find topics matching a pattern."""
        topic_pattern = TopicPattern(pattern)
        
        with self.lock:
            matching = []
            for topic_name in self.topics.keys():
                if topic_pattern.matches(topic_name):
                    matching.append(topic_name)
            return matching
    
    def get_topic_info(self, name: str) -> Optional[TopicInfo]:
        """Get topic information."""
        with self.lock:
            return self.topics.get(name)
    
    def list_topics(self, 
                   tag: Optional[str] = None,
                   pattern: Optional[str] = None) -> List[TopicInfo]:
        """
        List topics with optional filtering.
        
        Args:
            tag: Filter by tag
            pattern: Filter by pattern
            
        Returns:
            List of matching TopicInfo
        """
        with self.lock:
            topics = list(self.topics.values())
            
            if tag:
                topics = [t for t in topics if tag in t.tags]
            
            if pattern:
                topic_pattern = TopicPattern(pattern)
                topics = [t for t in topics if topic_pattern.matches(t.name)]
            
            return sorted(topics, key=lambda t: t.name)
    
    def add_subscription(self, subscription: Subscription):
        """Add subscription to registry."""
        with self.lock:
            # Register topic if not exists
            if subscription.topic not in self.topics:
                self.register_topic(subscription.topic)
            
            # Update counts
            topic_info = self.topics[subscription.topic]
            topic_info.subscriber_count += 1
            
            # Track subscription
            self.subscribers[subscription.topic].append(subscription.id)
            self.subscriptions[subscription.id] = subscription
    
    def remove_subscription(self, subscription_id: str):
        """Remove subscription from registry."""
        with self.lock:
            if subscription_id not in self.subscriptions:
                return
            
            subscription = self.subscriptions[subscription_id]
            topic = subscription.topic
            
            # Update counts
            if topic in self.topics:
                self.topics[topic].subscriber_count -= 1
            
            # Remove tracking
            if subscription_id in self.subscribers[topic]:
                self.subscribers[topic].remove(subscription_id)
            
            del self.subscriptions[subscription_id]
    
    def record_message(self, topic: str):
        """Record message publication for topic."""
        with self.lock:
            if topic not in self.topics:
                self.register_topic(topic)
            
            topic_info = self.topics[topic]
            topic_info.message_count += 1
            topic_info.last_message_at = __import__('time').time()
    
    def get_topic_hierarchy(self) -> Dict[str, Any]:
        """Get hierarchical view of topics."""
        with self.lock:
            hierarchy = {}
            
            for topic_name in self.topics.keys():
                parts = topic_name.split('.')
                current = hierarchy
                
                for part in parts:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                
                # Mark as leaf
                current['__topic__'] = topic_name
            
            return hierarchy
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        with self.lock:
            total_topics = len(self.topics)
            total_subscriptions = len(self.subscriptions)
            total_messages = sum(t.message_count for t in self.topics.values())
            
            # Active topics (with recent messages)
            current_time = __import__('time').time()
            active_topics = sum(
                1 for t in self.topics.values() 
                if t.last_message_at and (current_time - t.last_message_at) < 3600
            )
            
            # Topics by tag
            tags_count = defaultdict(int)
            for topic in self.topics.values():
                for tag in topic.tags:
                    tags_count[tag] += 1
            
            return {
                'total_topics': total_topics,
                'active_topics': active_topics,
                'total_subscriptions': total_subscriptions,
                'total_messages': total_messages,
                'patterns_registered': len(self.patterns),
                'tags_distribution': dict(tags_count)
            }
    
    def export_schema(self) -> Dict[str, Any]:
        """Export registry schema for documentation."""
        with self.lock:
            schema = {
                'topics': {},
                'patterns': []
            }
            
            for name, info in self.topics.items():
                schema['topics'][name] = {
                    'description': info.description,
                    'schema': info.schema,
                    'tags': list(info.tags),
                    'subscriber_count': info.subscriber_count,
                    'message_count': info.message_count
                }
            
            for pattern in self.patterns:
                schema['patterns'].append(pattern.pattern)
            
            return schema
    
    def validate_message(self, topic: str, payload: Any) -> bool:
        """Validate message against topic schema."""
        topic_info = self.get_topic_info(topic)
        if not topic_info or not topic_info.schema:
            return True  # No schema means no validation
        
        try:
            # Simple schema validation (could use jsonschema library)
            schema = topic_info.schema
            return self._validate_against_schema(payload, schema)
        except Exception:
            return False
    
    def _validate_against_schema(self, data: Any, schema: Dict[str, Any]) -> bool:
        """Simple schema validation implementation."""
        if 'type' in schema:
            expected_type = schema['type']
            if expected_type == 'object' and not isinstance(data, dict):
                return False
            elif expected_type == 'array' and not isinstance(data, list):
                return False
            elif expected_type == 'string' and not isinstance(data, str):
                return False
            elif expected_type == 'number' and not isinstance(data, (int, float)):
                return False
            elif expected_type == 'boolean' and not isinstance(data, bool):
                return False
        
        if 'properties' in schema and isinstance(data, dict):
            for prop, prop_schema in schema['properties'].items():
                if prop in data:
                    if not self._validate_against_schema(data[prop], prop_schema):
                        return False
        
        return True


class TopicRouter:
    """
    Advanced topic routing with load balancing and failover.
    """
    
    def __init__(self, registry: TopicRegistry):
        self.registry = registry
        self.routing_table: Dict[str, List[str]] = {}  # pattern -> topics
        self.load_balancer_state: Dict[str, int] = defaultdict(int)
        self.lock = threading.RLock()
    
    def add_route(self, pattern: str, target_topics: List[str]):
        """Add routing rule."""
        with self.lock:
            self.routing_table[pattern] = target_topics
    
    def route_message(self, topic: str) -> List[str]:
        """Route message to appropriate topics."""
        with self.lock:
            targets = [topic]  # Always include original topic
            
            # Check routing rules
            for pattern, target_topics in self.routing_table.items():
                if TopicPattern(pattern).matches(topic):
                    targets.extend(target_topics)
            
            return list(set(targets))  # Remove duplicates
    
    def get_next_target(self, targets: List[str]) -> str:
        """Get next target using round-robin load balancing."""
        if not targets:
            raise ValueError("No targets available")
        
        if len(targets) == 1:
            return targets[0]
        
        # Round-robin load balancing
        key = '|'.join(sorted(targets))
        with self.lock:
            index = self.load_balancer_state[key] % len(targets)
            self.load_balancer_state[key] += 1
            return targets[index]
