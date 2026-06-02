# Eval results -- Infosys FY24 RAG

**Ran at (UTC):** 2026-06-02T06:57:46+00:00  
**Model:** gpt-4o-mini  
**Retrieval:** hybrid (vector + BM25, RRF k=60, top-8)  
**Source doc:** data/infosys_ar.pdf (Infosys FY24 annual report, 359 pages)  

## Summary

- Auto-pass: **10 / 12**
- Total API cost: **$0.0061**
- Avg latency: **3.32 s/query**

Auto-grade is coarse (abstention correctness + expected-substring presence).
The per-question table below is the canonical scoring view -- edit the
**Manual** column after reading each answer.

## Per-question results

### `fl_001` (fact_lookup) -- auto: PASS

**Q:** Who is the current CEO of Infosys?

**Expected:** real answer containing `Salil Parekh`

**Answer:**

> The current CEO of Infosys is Salil Parekh, who also serves as the Managing Director (p. 94).

- abstained: `False`  - cited pages: `[94]`  - sources retrieved: `[94, 86, 85, 83, 281, 236, 265, 272]`  - latency: 3.66s  - cost: $0.00046
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `fl_002` (fact_lookup) -- auto: PASS

**Q:** When was Infosys founded?

**Expected:** real answer containing `1981`

**Answer:**

> Infosys was founded on July 2, 1981 (p. 39).

- abstained: `False`  - cited pages: `[39]`  - sources retrieved: `[62, 100, 83, 39, 269, 217, 268, 93]`  - latency: 3.12s  - cost: $0.00046
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `fl_003` (fact_lookup) -- auto: FAIL

**Q:** Where is Infosys's registered office located?

**Expected:** real answer containing `Bangalore`

**Answer:**

> Infosys's registered office is located at Electronics City, Hosur Road, Bengaluru, Karnataka, India 560 100 (p. 1).

- abstained: `False`  - cited pages: `[1]`  - sources retrieved: `[1, 59, 100, 143, 62, 320, 39, 244]`  - latency: 3.1s  - cost: $0.00048
- auto-grade reason: answer missing expected substring 'Bangalore'
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tr_001` (trend) -- auto: PASS

**Q:** How has Infosys's total employee count changed in recent years?

**Expected:** real answer containing `employees`

**Answer:**

> Between March 31, 2021, and March 31, 2025, Infosys's total employees grew from 259,619 to 323,578, representing a compound annualized growth rate of 5.7% (p. 39).

- abstained: `False`  - cited pages: `[39]`  - sources retrieved: `[107, 56, 100, 177, 39, 80, 57, 71]`  - latency: 2.23s  - cost: $0.00052
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tr_002` (trend) -- auto: FAIL

**Q:** What has been the trend in Infosys's R&D expenditure as a percentage of revenue?

**Expected:** real answer containing `R&D`

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include information about Infosys's R&D expenditure or its percentage of revenue.

- abstained: `True`  - cited pages: `[]`  - sources retrieved: `[237, 66, 39, 74, 38, 157, 62, 199]`  - latency: 2.12s  - cost: $0.00049
- auto-grade reason: abstained when an answer was expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `sy_001` (synthesis) -- auto: PASS

**Q:** Summarize Infosys's strategy around generative AI and Topaz from the report.

**Expected:** real answer containing `Topaz`

**Answer:**

> Infosys's strategy around generative AI is centered on leveraging its Infosys Topaz® platform, which encompasses a suite of AI-first services, solutions, and tools designed to enhance adaptability and flexibility for businesses. The company has successfully delivered over 400 generative AI projects, focusing on improving customer interactions, marketing efficiencies, code quality, and overall organizational productivity (pp. 40, 53). Infosys aims to help enterprises build resilience and drive innovation through AI, positioning itself as a partner in navigating digital transformation (p. 41). The emphasis on collaboration with various partners, including hyper-scalers and startups, further strengthens its capabilities in delivering tailored AI solutions (p. 53).

- abstained: `False`  - cited pages: `[40, 53, 41]`  - sources retrieved: `[53, 40, 52, 62, 49, 39, 41, 108]`  - latency: 4.59s  - cost: $0.00051
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `sy_002` (synthesis) -- auto: PASS

**Q:** What are the main competitive and regulatory risks Infosys discloses?

**Expected:** real answer containing `competition`

**Answer:**

> Infosys identifies several competitive and regulatory risks in its annual report:
> 
> - **Client Dependency**: A significant portion of revenues relies on a limited number of clients, meaning the loss of any major client could severely impact the business (p. 5).
> - **Financial Stability of Clients**: Factors like demand and supply challenges, currency fluctuations, and geopolitical conflicts may affect clients' financial stability, impacting Infosys's ability to recover fees (p. 5).
> - **Intense Competition**: The technology services market is highly competitive, which could affect win rates and pricing, potentially reducing market share and profits (p. 5).
> - **Regulatory Compliance**: Changes in regulations, such as tax benefits or incentives from the Government of India, could adversely affect net income (p. 32).
> 
> These risks highlight the challenges Infosys faces in maintaining its competitive edge and complying with regulatory requirements.

- abstained: `False`  - cited pages: `[5, 32]`  - sources retrieved: `[152, 5, 28, 151, 12, 153, 62, 32]`  - latency: 4.4s  - cost: $0.00054
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `sy_003` (synthesis) -- auto: PASS

**Q:** How does Infosys describe its approach to environmental sustainability and net-zero commitments?

**Expected:** real answer containing `carbon`

**Answer:**

> Infosys has articulated its commitment to environmental sustainability through its ESG Vision 2030, which aims to "shape and share solutions that serve the development of businesses and communities." As part of this vision, Infosys has maintained carbon neutrality for six consecutive years and has refreshed its ambitions to become climate positive by 2030. This involves implementing initiatives to reduce greenhouse gas emissions across scope 1, 2, and 3, sequestering more carbon than it emits, and moving beyond net zero. Additionally, Infosys is focused on empowering over 18 million people through digital skilling programs and creating sustainable communities through various CSR efforts, including healthcare and women's empowerment (pp. 63, 100).

- abstained: `False`  - cited pages: `[63, 100]`  - sources retrieved: `[28, 100, 39, 101, 77, 107, 63, 153]`  - latency: 3.85s  - cost: $0.00054
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tb_001` (table_lookup) -- auto: PASS

**Q:** What is the geographic revenue breakdown for Infosys (by region)?

**Expected:** real answer containing `North America`

**Answer:**

> The geographic revenue breakdown for Infosys for the last three fiscal years is as follows:
> 
> - **North America**: 
>   - Fiscal 2025: 57.9%
>   - Fiscal 2024: 60.1%
>   - Fiscal 2023: 61.8%
>   
> - **Europe**: 
>   - Fiscal 2025: 29.8%
>   - Fiscal 2024: 27.6%
>   - Fiscal 2023: 25.7%
>   
> - **Rest of the World**: 
>   - Fiscal 2025: 9.2%
>   - Fiscal 2024: 9.8%
>   - Fiscal 2023: 9.9%
>   
> - **India**: 
>   - Fiscal 2025: 3.1%
>   - Fiscal 2024: 2.5%
>   - Fiscal 2023: 2.6% (p. 56).

- abstained: `False`  - cited pages: `[56]`  - sources retrieved: `[70, 237, 38, 216, 62, 56, 201, 203]`  - latency: 4.5s  - cost: $0.0006
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `tb_002` (table_lookup) -- auto: PASS

**Q:** What were Infosys's operating segments and their relative revenue contributions?

**Expected:** real answer containing `Financial Services`

**Answer:**

> Infosys's operating segments and their relative revenue contributions for fiscal 2025 were as follows:
> 
> - Financial Services: 27.7%
> - Retail: 13.5%
> - Communications: 11.7%
> - Energy, Utilities, Resources and Services: 13.3%
> - Manufacturing: 15.5%
> - Hi-Tech: 8.0%
> - Life Sciences: 7.3%
> - All Other segments: 3.0% (p. 56).

- abstained: `False`  - cited pages: `[56]`  - sources retrieved: `[201, 237, 66, 203, 39, 65, 56, 304]`  - latency: 4.62s  - cost: $0.00056
- auto-grade reason: substring matched
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `ab_001` (abstention) -- auto: PASS

**Q:** What is Infosys's current stock price?

**Expected:** abstention (no answer in the doc)

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include information about Infosys's current stock price.

- abstained: `True`  - cited pages: `[]`  - sources retrieved: `[114, 38, 334, 255, 216, 356, 62, 305]`  - latency: 1.91s  - cost: $0.00047
- auto-grade reason: abstained as expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

### `ab_002` (abstention) -- auto: PASS

**Q:** What were Infosys's revenue numbers for fiscal year 2026?

**Expected:** abstention (no answer in the doc)

**Answer:**

> INSUFFICIENT_CONTEXT: The provided context does not include revenue numbers for fiscal year 2026.

- abstained: `True`  - cited pages: `[]`  - sources retrieved: `[77, 226, 38, 265, 39, 227, 62, 142]`  - latency: 1.79s  - cost: $0.00048
- auto-grade reason: abstained as expected
- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_

