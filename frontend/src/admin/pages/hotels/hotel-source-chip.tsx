/** hotel-source-chip.tsx — NGUỒN column (phase-07-hotels-list.md checklist).
 * `is_manual` is the one flag every other L19/L20/L21 mitigation hangs off
 * of: a manual hotel is admin-owned and safe to edit freely; a
 * pipeline-sourced one gets the striped row treatment in hotels-table.tsx
 * because a re-run of the ETL will overwrite hand edits. */
export function HotelSourceChip({ isManual }: { isManual: boolean }) {
  if (isManual) {
    return <span className="source-chip source-chip--manual">✎ Tự nhập</span>
  }
  return <span className="source-chip source-chip--pipeline">⟳ Từ pipeline</span>
}
