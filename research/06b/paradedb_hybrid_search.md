### SOURCE: https://www.paradedb.com/docs/reference/hybrid/overview.md

> ## Documentation Index
> Fetch the complete documentation index at: https://www.paradedb.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hybrid Search

> Reference pages for combining full-text and vector rankings

<Note>
  Hybrid search uses [vector search](/docs/reference/vector/overview), a beta feature
  available in versions `0.25.0` and above.
</Note>

Use these pages when you need the exact SQL shape for hybrid ranking in
ParadeDB. For the mental model, see [How Hybrid Search Works](/docs/concepts/hybrid/overview).

<CardGroup cols={2}>
  <Card title="Reciprocal Rank Fusion" icon="shuffle" href="/docs/reference/hybrid/rrf">
    Merge full-text and vector result lists by rank.
  </Card>

  <Card title="Querying Vectors" icon="chart-scatter" href="/docs/reference/vector/querying">
    Run the vector branch used in hybrid search.
  </Card>

  <Card title="BM25 Scoring" icon="gauge" href="/docs/reference/full-text/score">
    Rank the full-text branch by ParadeDB relevance score.
  </Card>
</CardGroup>

