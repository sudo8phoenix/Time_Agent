# Evaluation units and denominators

An evaluation must state its unit before computing a rate. The following units
apply across the repository; a result for one unit does not imply another.

| Unit | Identity and denominator | Important boundary |
|---|---|---|
| Source document | Source file ID plus content hash/version; denominator is documents | Multiple pages/scans belong to the same source family; preserve raw bytes and parsing lineage |
| Report | Report ID plus immutable version; denominator is reports | One report can contain many documents/fragments and atomic events |
| Fragment | Report version plus canonical fragment ID; denominator is fragments | Preserve source locator, extracted text and correction history; nearby fragments are not independent held-out reports |
| Atomic event | Case/report plus a full assertion tuple or explicit stable event locator; denominator is all labelled assertions | Event type alone cannot align repeated same-type assertions; multisets preserve duplicates and detect omissions |
| Event-to-activity link | Atomic event identity plus schedule version and proposed/expected activity; denominator states all matchable events, emitted selections, or ambiguous/unmatched events | Recall, selected precision, coverage and safe abstention have distinct denominators; missing/failed output is not verified abstention |
| Conversation | Conversation/session ID plus ordered turn versions; denominator is conversations | Multi-turn repairs and corrections remain within the conversation; turns are correlated |
| Complete delivery | Durable submission/report version plus delivery idempotency identity; denominator is every submitted eligible workflow | Success requires all required extraction/retrieval/review/approval/update/acknowledgement outcomes; failure, cancellation and timeout remain visible |

Experiments additionally identify scheduled trials by case, arm and repetition.
Scheduled trials include unattempted, failed and completed outcomes. Repetition
never creates a fresh independent source family. Project/report/source-family
clusters govern split integrity and uncertainty; report micro and project macro
metrics with their own denominators. Raw model output and normalized/persisted
output are separate measurement stages. One successful stage or a mock PMIS
acknowledgement does not prove complete real delivery.

All field-specific metrics must report their applicability inventory. An absent
annotation is unscored; an explicitly annotated null is scored and requires an
actually present null output. Alternative annotations must be explicit coherent
whole-event/case alternatives; report matches and unresolved review status.
