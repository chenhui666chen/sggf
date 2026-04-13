export interface SettingCollection {
  id: number
  project_id: number
  name: string
  category?: string | null
  description?: string | null
  order: number
  max_depth?: number | null
  hierarchy_config?: string | null
  created_at: string
  updated_at?: string | null
}

export interface SettingCollectionCreatePayload {
  name: string
  category?: string | null
  description?: string | null
  order?: number
  max_depth?: number | null
  hierarchy_config?: string | null
}

export interface SettingCollectionUpdatePayload {
  name?: string
  category?: string | null
  description?: string | null
  order?: number
  max_depth?: number | null
  hierarchy_config?: string | null
}

export interface SettingItem {
  id: number
  collection_id: number
  name: string
  code?: string | null
  level?: number | null
  tags?: string[] | null
  content?: string | null
  relations?: Record<string, unknown> | null
  order: number
  depth?: number | null
  node_type?: string | null
  is_leaf?: boolean | null
  path?: string | null
  summary?: string | null
  created_at: string
  updated_at?: string | null
  snapshots?: string | null
  confidence_score?: number | null
}

export interface SettingItemCreatePayload {
  name: string
  code?: string | null
  level?: number | null
  tags?: string[] | null
  content?: string | null
  relations?: Record<string, unknown> | null
  order?: number
  depth?: number | null
  node_type?: string | null
  is_leaf?: boolean | null
  path?: string | null
  summary?: string | null
}

export interface SettingItemUpdatePayload {
  name?: string
  code?: string | null
  level?: number | null
  tags?: string[] | null
  content?: string | null
  relations?: Record<string, unknown> | null
  order?: number
  depth?: number | null
  node_type?: string | null
  is_leaf?: boolean | null
  path?: string | null
  summary?: string | null
}

export interface SettingTreeApiNode {
  name: string
  depth: number | null
  is_leaf: boolean
  item: SettingItem | null
  children: SettingTreeApiNode[]
}

export interface SettingItemsTreeResponse {
  collection: string
  tree: SettingTreeApiNode[]
}

export interface SettingTreeActionItem extends Partial<SettingItem> {
  name: string
  path?: string | null
  is_leaf?: boolean | null
}

export interface SettingTemplateCollectionInfo {
  name: string
  category: string
}

export interface SettingTemplateMetadata {
  key: string
  name: string
  description: string
  collections_count: number
  collections: SettingTemplateCollectionInfo[]
}

export interface SettingSmartExtractItem {
  id: number
  name: string
  content?: string | null
  tags?: string[] | null
}

export interface SettingSmartExtractRelatedContent {
  chapter_id: number
  chapter_number: number
  chapter_title: string
  excerpt: string
  confidence: number
  ai_validated?: boolean
}

export interface SettingSmartExtractResponse {
  item?: SettingSmartExtractItem
  item_name?: string
  related_contents: SettingSmartExtractRelatedContent[]
  suggested_tags: string[]
  collection_category?: string | null
}
