# Fast hotel search benchmark

Live database benchmark against `V_OTA`, using one stored hotel embedding as
the query vector and requesting five results without date or price filters.

| Function | Change | Result | Execution time |
| --- | --- | --- | --- |
| `match_hotels_with_rooms` | Legacy implementation scores all hotel and room vectors before limiting results. | 5 hotels | 5,231 ms |
| `match_hotels_with_rooms_fast` | Retrieves bounded nearest-neighbor candidates from the existing HNSW indexes (100 candidates for a five-result request), then applies the same filters and aggregation. | Same ranked 5 hotel IDs as legacy | 1,787 ms |

The fast function is service-role-only and exists alongside the legacy RPC.
This preserves an immediate rollback path while the backend is switched in a
separate change.
