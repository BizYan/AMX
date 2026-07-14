CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name varchar(255) NOT NULL DEFAULT 'candidate-project',
  description text,
  slug varchar(100) NOT NULL DEFAULT 'candidate-project',
  status varchar(20) NOT NULL DEFAULT 'active',
  owner_id uuid,
  tenant_id uuid,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  deleted_at timestamp with time zone
);

CREATE TABLE IF NOT EXISTS documents (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  doc_type varchar(50) NOT NULL DEFAULT 'urs',
  title varchar(500) NOT NULL DEFAULT 'candidate-document',
  content text NOT NULL DEFAULT '',
  status varchar(20) NOT NULL DEFAULT 'draft',
  version integer NOT NULL DEFAULT 1,
  parent_document_id uuid,
  created_by uuid NOT NULL DEFAULT uuid_generate_v4(),
  approved_by uuid,
  quality_score double precision,
  metadata_json jsonb,
  tenant_id uuid,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  deleted_at timestamp with time zone
);
