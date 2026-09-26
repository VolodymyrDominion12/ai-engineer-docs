### SOURCE: https://docs.paradedb.com/documentation/full-text/overview.md

> ## Documentation Index
> Fetch the complete documentation index at: https://www.paradedb.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# How Text Search Works

> Understand how ParadeDB uses token matching to efficiently search large corpuses of text

Text search in ParadeDB, like Elasticsearch and most search engines, is centered around the concept of **token matching**.

Token matching consists of two steps. First, at indexing time, text is processed by a tokenizer, which breaks input into discrete units called **tokens** or
**terms**. For example, the [default](/docs/reference/indexing/create-index) tokenizer splits the text `Sleek running shoes` into the tokens `sleek`, `running`, and `shoes`.

Second, at query time, the query engine looks for token matches based on the specified query and query type. Some common query types include:

* [Match](/docs/reference/full-text/match): Matches documents containing any or all query tokens
* [Phrase](/docs/reference/full-text/phrase): Matches documents where all tokens appear in the same order as the query
* [Term](/docs/reference/full-text/term): Matches documents containing an exact token
* ...and many more [advanced](/docs/reference/full-text/query-builder) query types

## Not Substring Matching

While ParadeDB supports substring matching via [regex](/docs/reference/full-text/regex) queries, it's important to note that token matching is **not** the
same as substring matching.

Token matching is a much more versatile and powerful technique. It enables relevance scoring, language-specific analysis, typo tolerance, and more expressive query types — capabilities that go far beyond simply looking for a sequence of characters.

## Similarity Search

Text search is different from similarity search, also known as vector search. Whereas text search matches based on token matches, similarity search
matches based on semantic meaning.

As of `0.25.0`, ParadeDB natively supports vector search inside its indexes. See [How Vector Search Works](/docs/concepts/vector/overview) to learn more.

The two are complementary, and can be combined into a single ranking. See [How Hybrid Search Works](/docs/concepts/hybrid/overview).

