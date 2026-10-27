# Roadmap

What we would build next with more time. Each item: what, why it matters, and the
Microsoft technology it would use. Everything here is **not built yet**; the README
describes only what exists.

## Data and ingestion
- **Auto-eventing from video.** Run a vision model over the broadcast feed to tag passes,
  shots and speeds automatically instead of relying on an event feed.
  *Why:* removes manual tagging and works for matches without event data.
  *Tech:* Azure AI Foundry vision models, Azure AI Video Indexer.
- **Player tracking data.** Real player speed and distance covered (today only ball speed
  is estimated from event timing).
  *Why:* the brief's speed and distance indicators need positions for every player.
  *Tech:* Azure Event Hubs for the tracking stream.
- **Many matches, one platform.** Bring every match into one place for season-level stats.
  *Why:* lets narratives compare a player against their own history.
  *Tech:* Microsoft Fabric pipelines and Lakehouse.

## Intelligence
- **Memory across matches (RAG).** Store past insights with vector search so commentary
  can say "his first goal since…".
  *Tech:* Azure Cosmos DB with vector search, or Azure Database for PostgreSQL with pgvector.

## Experience
- **More languages, including non-Latin scripts.** Needs a script-aware version of the
  text guard (today it rejects non-Latin text by design).
  *Tech:* Azure OpenAI, Azure AI Translator.

## Production
- **Scale to many simultaneous matches.**
  *Tech:* Azure Kubernetes Service (AKS) with autoscaling per match.

## Cut during the build
- **Dribble success rate.** Every dribble in the synthetic data is recorded as "lost", so a
  success rate would always read 0%. Next: extend the data generator to record successful
  dribbles too (the brief's "data innovation" track).
- **Measured ball and shot speed.** Event times are whole seconds, so speeds are estimates
  from distance over time, shown only when a save follows within 1-2 s. Next: sub-second
  timestamps or tracking data.
