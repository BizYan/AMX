"""Graph Normalizer Service

Normalizes RawArtifact graph output into standard KnowledgeEntry format.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.domains.providers.contracts import GraphifyOutput


@dataclass
class NormalizedGraphNode:
    """Normalized graph node in standard KnowledgeEntry format.

    Represents a single entity extracted from document content.
    """
    id: UUID
    entity_type: str  # e.g., "person", "organization", "concept", "event"
    entity_name: str  # Human-readable name
    properties_json: dict[str, Any]  # All node properties
    source_document_id: str  # Reference to source document
    provider_id: UUID
    version_id: UUID
    tenant_id: UUID
    project_id: UUID
    created_at: datetime


class UnresolvedGraphEdge:
    """Edge that could not be resolved due to missing source or target node.

    Tracks edges where source or target nodes could not be found,
    allowing the caller to decide how to handle them.
    """
    def __init__(
        self,
        source_entity: str | dict | None,
        target_entity: str | dict | None,
        relationship_type: str,
        properties_json: dict[str, Any],
        source_document_id: str,
        provider_id: UUID,
        version_id: UUID,
        tenant_id: UUID,
        project_id: UUID,
        created_at: datetime,
    ):
        self.source_entity = source_entity
        self.target_entity = target_entity
        self.relationship_type = relationship_type
        self.properties_json = properties_json
        self.source_document_id = source_document_id
        self.provider_id = provider_id
        self.version_id = version_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.created_at = created_at


@dataclass
class NormalizedGraphEdge:
    """Normalized graph edge in standard KnowledgeEntry format.

    Represents a relationship between two entities.
    """
    id: UUID
    source_node_id: UUID  # UUID of source entity
    target_node_id: UUID  # UUID of target entity
    relationship_type: str  # e.g., "works_for", "located_in", "related_to"
    properties_json: dict[str, Any]  # Edge properties (weight, confidence, etc.)
    source_document_id: str
    provider_id: UUID
    version_id: UUID
    tenant_id: UUID
    project_id: UUID
    created_at: datetime


class GraphNormalizer:
    """Service for normalizing Graphify output to standard KnowledgeEntry format.

    Converts raw graph extraction output into a normalized format suitable
    for storage in the knowledge layer.
    """

    def __init__(self):
        """Initialize GraphNormalizer."""
        pass

    async def normalize(
        self,
        provider_id: UUID,
        version_id: UUID,
        raw_output: GraphifyOutput,
        tenant_id: UUID,
        project_id: UUID,
        source_document_id: str | None = None,
    ) -> tuple[list[NormalizedGraphNode], list[NormalizedGraphEdge], list[UnresolvedGraphEdge]]:
        """Normalize Graphify output to standard format.

        Converts nodes, edges, and relationships from Graphify format to
        standard NormalizedGraphNode and NormalizedGraphEdge objects.

        Args:
            provider_id: Provider UUID that produced the output
            version_id: Provider version UUID
            raw_output: Raw output from Graphify
            tenant_id: Tenant UUID for multi-tenancy
            project_id: Project UUID
            source_document_id: Optional source document ID override

        Returns:
            Tuple of (normalized_nodes, normalized_edges, unresolved_edges)
        """
        nodes = []
        edges = []
        unresolved_edges = []
        now = datetime.now(timezone.utc)

        # Track entity name to node ID mapping for edge resolution
        entity_to_node_id: dict[str, UUID] = {}

        # Process nodes
        doc_id = source_document_id or raw_output.metadata.get("document_id", "unknown") if raw_output.metadata else "unknown"

        for node_data in raw_output.nodes:
            node_id = uuid4()
            entity_type = node_data.get("type", "unknown")
            entity_name = node_data.get("name", node_data.get("id", "unnamed"))

            # Collect all properties
            properties = node_data.get("properties", {})
            properties.update({
                "original_id": node_data.get("id"),
                "entity_type": entity_type,
            })

            # Create normalized node
            normalized_node = NormalizedGraphNode(
                id=node_id,
                entity_type=entity_type,
                entity_name=entity_name,
                properties_json=properties,
                source_document_id=doc_id,
                provider_id=provider_id,
                version_id=version_id,
                tenant_id=tenant_id,
                project_id=project_id,
                created_at=now,
            )
            nodes.append(normalized_node)

            # Map entity for edge resolution
            entity_key = f"{entity_type}:{entity_name}"
            entity_to_node_id[entity_key] = node_id
            # Also map by original_id for edge resolution
            original_id = node_data.get("id")
            if original_id:
                entity_to_node_id[f"id:{original_id}"] = node_id

        # Process edges
        for edge_data in raw_output.edges:
            edge_id = uuid4()

            # Resolve source and target node IDs
            source_entity = edge_data.get("source")
            target_entity = edge_data.get("target")

            source_node_id = None
            target_node_id = None

            if source_entity:
                source_key = self._resolve_entity_key(source_entity, entity_to_node_id)
                source_node_id = entity_to_node_id.get(source_key)

            if target_entity:
                target_key = self._resolve_entity_key(target_entity, entity_to_node_id)
                target_node_id = entity_to_node_id.get(target_key)

            relationship_type = edge_data.get("type", edge_data.get("relationship", "related_to"))

            # If we can't resolve nodes, track as unresolved instead of creating fake references
            if source_node_id is None or target_node_id is None:
                edge_properties = edge_data.get("properties", {})
                edge_properties.update({
                    "original_edge_id": edge_data.get("id"),
                    "relationship_type": relationship_type,
                })
                unresolved_edge = UnresolvedGraphEdge(
                    source_entity=source_entity,
                    target_entity=target_entity,
                    relationship_type=relationship_type,
                    properties_json=edge_properties,
                    source_document_id=doc_id,
                    provider_id=provider_id,
                    version_id=version_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    created_at=now,
                )
                unresolved_edges.append(unresolved_edge)
                continue

            # Collect edge properties
            properties = edge_data.get("properties", {})
            properties.update({
                "original_edge_id": edge_data.get("id"),
                "relationship_type": relationship_type,
            })

            # Create normalized edge
            normalized_edge = NormalizedGraphEdge(
                id=edge_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                relationship_type=relationship_type,
                properties_json=properties,
                source_document_id=doc_id,
                provider_id=provider_id,
                version_id=version_id,
                tenant_id=tenant_id,
                project_id=project_id,
                created_at=now,
            )
            edges.append(normalized_edge)

        # Process relationships (may create additional nodes/edges)
        for rel_data in raw_output.relationships:
            rel_type = rel_data.get("type", "related_to")
            rel_source = rel_data.get("source")
            rel_target = rel_data.get("target")

            if rel_source and rel_target:
                source_key = self._resolve_entity_key(rel_source, entity_to_node_id)
                target_key = self._resolve_entity_key(rel_target, entity_to_node_id)

                source_id = entity_to_node_id.get(source_key)
                target_id = entity_to_node_id.get(target_key)

                if source_id and target_id:
                    # Add as an edge if both nodes exist
                    edge_id = uuid4()
                    normalized_edge = NormalizedGraphEdge(
                        id=edge_id,
                        source_node_id=source_id,
                        target_node_id=target_id,
                        relationship_type=rel_type,
                        properties_json=rel_data.get("properties", {}),
                        source_document_id=doc_id,
                        provider_id=provider_id,
                        version_id=version_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        created_at=now,
                    )
                    edges.append(normalized_edge)

        return nodes, edges, unresolved_edges

    def _resolve_entity_key(self, entity: str | dict, entity_map: dict[str, UUID]) -> str | None:
        """Resolve entity reference to a map key.

        Args:
            entity: Entity as string (name) or dict with type/name
            entity_map: Map of entity keys to node IDs

        Returns:
            Entity key string if found
        """
        if isinstance(entity, str):
            # First try exact match for type:name format
            if entity in entity_map:
                return entity
            # Try to find by name only
            for key in entity_map:
                if key.endswith(f":{entity}"):
                    return key
            # Try to find by id prefix
            if entity.startswith("id:"):
                return entity
            for key in entity_map:
                if key.startswith("id:") and key[3:] == entity:
                    return key
            # If no match, return as-is and let caller handle
            return entity
        elif isinstance(entity, dict):
            entity_type = entity.get("type", "unknown")
            entity_name = entity.get("name", entity.get("id", ""))
            return f"{entity_type}:{entity_name}"
        return None

    def node_to_dict(self, node: NormalizedGraphNode) -> dict[str, Any]:
        """Convert NormalizedGraphNode to dictionary.

        Args:
            node: Normalized node

        Returns:
            Dictionary representation
        """
        return {
            "id": str(node.id),
            "entity_type": node.entity_type,
            "entity_name": node.entity_name,
            "properties": node.properties_json,
            "source_document_id": node.source_document_id,
            "provider_id": str(node.provider_id),
            "version_id": str(node.version_id),
            "tenant_id": str(node.tenant_id),
            "project_id": str(node.project_id),
            "created_at": node.created_at.isoformat(),
        }

    def edge_to_dict(self, edge: NormalizedGraphEdge) -> dict[str, Any]:
        """Convert NormalizedGraphEdge to dictionary.

        Args:
            edge: Normalized edge

        Returns:
            Dictionary representation
        """
        return {
            "id": str(edge.id),
            "source_node_id": str(edge.source_node_id),
            "target_node_id": str(edge.target_node_id),
            "relationship_type": edge.relationship_type,
            "properties": edge.properties_json,
            "source_document_id": edge.source_document_id,
            "provider_id": str(edge.provider_id),
            "version_id": str(edge.version_id),
            "tenant_id": str(edge.tenant_id),
            "project_id": str(edge.project_id),
            "created_at": edge.created_at.isoformat(),
        }