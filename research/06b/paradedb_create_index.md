### SOURCE: https://www.paradedb.com/docs/start/create-your-first-index.md

> ## Documentation Index
> Fetch the complete documentation index at: https://www.paradedb.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Your First Index

> Create a ParadeDB index over your table

Create a ParadeDB index over the `mock_items` table from [Connect Your
App](/docs/start/connect-your-app). The same index supports text
search, vector search, filtering, sorting, and aggregations in the next page.

<CodeGroup>
  ```sql SQL theme={null}
  CREATE INDEX search_idx ON mock_items
  USING paradedb (
    id,
    description,
    embedding vector_cosine_ops,
    category,
    rating,
    in_stock,
    created_at,
    last_updated_date,
    latest_available_time,
    metadata,
    weight_range
  )
  WITH (key_field='id');
  ```

  ```ts Drizzle theme={null}
  import { sql } from "drizzle-orm";

  await db.execute(sql`
    CREATE INDEX search_idx ON mock_items
    USING paradedb (
      id,
      description,
      embedding vector_cosine_ops,
      category,
      rating,
      in_stock,
      created_at,
      last_updated_date,
      latest_available_time,
      metadata,
      weight_range
    )
    WITH (key_field='id')
  `);
  ```

  ```python Django theme={null}
  from django.db import connection

  with connection.cursor() as cursor:
      cursor.execute("""
          CREATE INDEX search_idx ON mock_items
          USING paradedb (
            id,
            description,
            embedding vector_cosine_ops,
            category,
            rating,
            in_stock,
            created_at,
            last_updated_date,
            latest_available_time,
            metadata,
            weight_range
          )
          WITH (key_field='id')
      """)
  ```

  ```python SQLAlchemy theme={null}
  from sqlalchemy import text

  with engine.begin() as conn:
      conn.execute(text("""
          CREATE INDEX search_idx ON mock_items
          USING paradedb (
            id,
            description,
            embedding vector_cosine_ops,
            category,
            rating,
            in_stock,
            created_at,
            last_updated_date,
            latest_available_time,
            metadata,
            weight_range
          )
          WITH (key_field='id')
      """))
  ```

  ```ruby Rails theme={null}
  ActiveRecord::Base.connection.execute <<~SQL
    CREATE INDEX search_idx ON mock_items
    USING paradedb (
      id,
      description,
      embedding vector_cosine_ops,
      category,
      rating,
      in_stock,
      created_at,
      last_updated_date,
      latest_available_time,
      metadata,
      weight_range
    )
    WITH (key_field='id');
  SQL
  ```

  ```cs EF Core theme={null}
  await dbContext.Database.ExecuteSqlRawAsync("""
      CREATE INDEX search_idx ON mock_items
      USING paradedb (
        id,
        description,
        embedding vector_cosine_ops,
        category,
        rating,
        in_stock,
        created_at,
        last_updated_date,
        latest_available_time,
        metadata,
        weight_range
      )
      WITH (key_field='id');
      """);
  ```
</CodeGroup>

<Note>
  If `search_idx` already exists, drop it first with `DROP INDEX search_idx;`.
</Note>

The first indexed column, `id`, is also the `key_field`. ParadeDB uses the key
field as the row's stable identifier inside the index. In your own schema, use a
primary key or another column with a `UNIQUE` constraint. See [Choosing a Key
Field](/docs/reference/indexing/create-index#choosing-a-key-field) for the full
rules.

Everything after `id` is a field you can search, filter, sort, group, or
aggregate. The `description` column is indexed for full-text search, `embedding`
is indexed for vector search, and fields like `rating`, `category`, and
`created_at` are available for filters, Top K queries, and facets.

For production schemas, define this index in your migration system instead of
running ad hoc SQL. The full [Create an
Index](/docs/reference/indexing/create-index) reference includes framework-native
examples and tokenizer options.

Next, [run your first queries](/docs/start/run-queries).

