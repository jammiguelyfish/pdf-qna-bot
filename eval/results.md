### Retrieval (is the answer chunk in the top 4?)

| Retriever | Hit rate | MRR |
|---|---|---|
| dense | 17/24 (71%) | 0.50 |
| bm25 | 23/24 (96%) | 0.78 |
| hybrid | 22/24 (92%) | 0.69 |

Missed by **dense**:
- Where are we going on January 15?
- Which island do we visit on January 25?
- How many nights are we staying in Busan?
- Where are we on October 20?
- Which cable car do we take in Busan?
- What day trip is on April 13?
- What do we do on April 16?

Missed by **bm25**:
- Where are we going on January 15?

Missed by **hybrid**:
- Where are we on October 20?
- Which cable car do we take in Busan?

### Answers (`qwen2.5:1.5b-instruct`, hybrid retriever)

- Answerable questions correct: 20/24
- Unanswerable questions refused: 2/3

Wrong answers:
- Where are we on October 20? -> "I don't know based on the provided document."
- Which temple do we visit on the east coast of Busan? -> 'Seoudong Yonggungsa Temple'
- Which cable car do we take in Busan? -> 'We take the cable car up Namsan Mountain to N Seoul Tower for panoramic night views.'
- How far in advance should I book KTX tickets? -> "I don't know based on the provided document."
- Which airline do we fly from Jeju to Seoul? -> 'Fly from Jeju (CJU) to Seoul Gimpo Airport (GMP, approx. 1 hour 15 minutes) and transfer to Gangnam.'
