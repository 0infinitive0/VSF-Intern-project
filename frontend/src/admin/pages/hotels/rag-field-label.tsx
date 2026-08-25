/**
 * rag-field-label.tsx -- the "ảnh hưởng tìm kiếm của bot" tag next to fields
 * that feed the embedding text (phase-08-hotel-create.md L28). Backend's
 * `embedding_fields.EMBEDDING_FIELDS` is the actual source of truth for
 * which columns those are; this component only renders the tag where B2's
 * checklist puts it (Tên, Loại hình, Mô tả, Địa chỉ) -- it does not fetch or
 * derive the list, so it can't silently disagree with the backend without a
 * human noticing (see test_admin_hotels.py's subset assertion).
 */
export function RagFieldLabel() {
  return (
    <span style={{ fontSize: 11, color: 'var(--acc)', fontWeight: 500 }}>Ảnh hưởng tìm kiếm của chatbot</span>
  )
}
