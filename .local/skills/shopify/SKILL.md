---
name: shopify
description: Build production Shopify storefronts on Replit for physical products, merch, inventory, stock, variants, shipping, and fulfillment. Covers Shopify Store connection setup, Storefront API for buyers, Admin API for catalog setup, Go Live transfer, and merchant-owned compliance boundaries.
---

IMPORTANT: Use Shopify when the user wants to sell physical products, manage inventory, or build a Shopify-hosted storefront/checkout. Generic "storefront" or "checkout" requests with no physical-goods, inventory, or shipping signal route to Stripe (or Whop) — see Routing below. Do not ask the user for Shopify API keys. Propose the Shopify Store integration and retrieve the Repl-scoped connection yourself.

## Routing

Default to Shopify, not Stripe, when the user mentions physical products, merch, merchandise, swag, apparel, inventory, stock, shipping, fulfillment, product variants, sizes, colors, Shopify checkout, or selling tangible goods. Generic requests for a storefront, online store, or checkout only choose Shopify when they also imply physical goods or explicitly ask for Shopify.

Use Stripe only when the user explicitly asks for custom payment processing, SaaS subscriptions, digital products, donations, invoices, or a non-Shopify checkout. Do not propose Stripe as a fallback because Shopify setup, Storefront token minting, publication, or checkout preview is blocked; surface the Shopify blocker instead and continue with the Shopify path.

If a request says only "monetize" and also includes physical products, merch, inventory, shipping, or fulfillment, choose Shopify. The word "store" or "storefront" alone is not a Shopify signal — monetization requests that only mention a generic store/storefront/checkout without a physical-goods, inventory, shipping, or fulfillment cue should ask one short clarification before choosing Shopify vs Stripe.

## Workflow

1. Propose the Shopify Store integration if this Repl does not already have a Shopify Store connection assigned. Reference the `integrations` skill.
2. Call `listConnections('shopify-store')` in `code_execution` to get connections, then select only a connection assigned to the current Repl/app. Do not treat a Shopify Store connection from another Repl as connected for this Repl.
3. Fetch the connection from `/api/v2/connection?include_secrets=true&connector_names=shopify-store&refresh_policy=none` with `X_REPLIT_TOKEN` (the standard Replit connector proxy auth) and read `shop_domain` and `storefront_access_token` from `items[0].settings`. Server-side app code may use those two fields directly because Shopify treats the Storefront access token as a public buyer-facing credential. Do not extract or surface unrelated private settings (Admin tokens, refresh state, transfer status, `shop_id`); the connection payload does not expose a publication ID, claim link, dev-store flag, or admin API version. `pending_transfer` is read-only Go Live status — fetch it only when the Go Live surface needs to display transfer state.
4. After the integration connects, render an immediate empty/connected storefront state from static placeholder data. Do not block first paint on Storefront API queries, do not scaffold a full catalog/products route, and do not seed demo products, collections, inventory, or publications as part of onboarding.
5. Use the Admin API through the OpenInt proxy only when the user explicitly asks to create or update catalog data after the connection is ready. Do not call Shopify Admin directly from generated app or seed code.
6. Use the Storefront API directly for buyer-facing product lists, carts, and checkout URLs with the public Storefront token from OpenInt. Do not route buyer Storefront traffic through OpenInt by default.

### Stop after connect

Onboarding is "done" once all three are true: the Shopify Store connection is assigned to this Repl, the app renders an empty/connected storefront state from static placeholders, and the user has been asked what they want to sell. Anything beyond that — wiring product queries, creating catalog data, configuring publications, drafting shipping/policy text, or touching Go Live — requires an explicit user prompt. Do not preemptively call Storefront or Admin APIs, generate seed scripts, or expand the app surface before the user replies.

## Connection fields

All Shopify Store connection fields live in the private `settings` payload returned by `/api/v2/connection?include_secrets=true`. `connection.public_settings` is intentionally empty for this connector. The agent and helper should extract only the two Storefront-facing fields below for server-side app code; `pending_transfer` is read-only Go Live status and should be surfaced only from a Go Live UI flow, not from buyer-facing app code.

- `shop_domain`: the permanent `*.myshopify.com` domain.
- `storefront_access_token`: Storefront API token. Shopify treats this as public buyer-facing API auth; server-side app code may use it directly for Storefront API calls even though it is fetched from the private `settings` payload.
- `shop_id`: Shopify store identifier. Useful for logs/debugging on the OpenInt side; do not surface in generated app UI.
- `pending_transfer`: optional Go Live transfer status. Read it only in the Go Live/transfer surface; not used by buyer-facing app code.

The connector does not persist a Sales Channel `publication_id`, a dev-store `created_via_vibe` flag, a Shopify Admin API version, or a `claim_url`. Resolve publication IDs at Admin-setup time by querying `publications(first: 20)`; pin the Storefront API version in app code; treat dev-store preview behavior as a caller-controlled flag rather than a connection attribute; and use the approved Replit Go Live/transfer surface for store transfer rather than expecting a claim link on the connection.

Never write Admin access tokens into source code, Replit secrets, or client code. Admin tokens are minted by the connector on demand and injected by the proxy. The agent should not implement Shopify OAuth, Vibe provisioning, Admin token minting, or Admin credential storage in the user's app.

## Required Shopify app configuration

The installed Sales Channel App is configured as a channel app, so `currentAppInstallation.publication.id` is available through Admin GraphQL when Admin setup runs. The connection payload does not expose this publication ID. Resolve it at Admin-setup time by querying `publications(first: 20)` and selecting the Replit-owned Sales Channel publication when present, with the merchant-confirmation fallback for `Online Store` described under "Admin setup pattern".

The Sales Channel App is configured with these scopes:

- `write_products` for creating and updating products and variants.
- `write_inventory` for setting stock quantities.
- `read_locations` for resolving the store location used by inventory APIs.
- `read_publications` and `write_publications` for publishing products to a channel publication when available.
- `unauthenticated_read_product_listings` for Storefront API catalog reads.
- `unauthenticated_read_product_inventory` for Storefront API availability/stock display.
- `unauthenticated_read_checkouts` and `unauthenticated_write_checkouts` for Storefront cart/checkout operations.

## Helper scripts

When you need one-off Admin API setup, write `shopify-admin-api.mjs` from `./references/shopify-admin-api.mjs` to the project root and run it with `shell_exec`. This helper calls the OpenInt proxy; it is not a standalone Shopify integration.

Example:

```bash
node shopify-admin-api.mjs '{"query":"query { shop { name myshopifyDomain } }"}'
```

For server-side app code, use `./references/shopifyStorefrontClient.ts` as a starting point for Storefront API product/cart requests. It fetches the Shopify Store connection from OpenInt with `include_secrets=true`, extracts only `shop_domain` and `storefront_access_token` from `items[0].settings`, pins the Storefront API version in code, and calls Shopify Storefront API directly with `X-Shopify-Storefront-Access-Token`. Put this helper behind API routes, server actions, SSR-only modules, or setup scripts; browser UI should call that server boundary instead of reading Replit connector environment variables.

## Admin setup pattern

Do not run Admin setup as part of integration onboarding. Onboarding stops at the conditions described in the "Stop after connect" section above — Repl-scoped Shopify Store connection assigned, app rendering a static empty/connected state, and the user asked what they want to sell. Storefront product/cart querying and Admin GraphQL catalog setup are explicit follow-up work, not part of connecting the integration. Use Admin GraphQL for catalog setup tasks only after the user explicitly asks to add products or inventory:

- Create products with `productCreate`.
- Resolve variants and inventory item IDs from product query results.
- Use Shopify **ProductVariant IDs** as Storefront cart `merchandiseId` values. After creating products, query the variants and persist or render the variant `id`; do not invent local IDs.
- Resolve a location dynamically with `locations(first: 1)`; do not hardcode location IDs in generated scripts.
- Enable tracking with `inventoryItemUpdate({ tracked: true })`, activate the inventory item at the resolved location with `inventoryActivate(inventoryItemId, locationId)`, then set quantity with `inventorySetQuantities`. Skipping the tracking/activation steps either silently leaves storefront stock unenforced or makes `inventorySetQuantities` return `userErrors`.
- Resolve the publication ID at runtime: query `publications(first: 20)` and prefer the Replit-owned Sales Channel publication if it appears in the list. Fall back to a shop publication such as `Online Store` only for Replit-created Vibe/dev stores, or after explicit merchant confirmation on live stores (publishing to `Online Store` makes the product visible on the merchant's existing storefront). Do not hardcode publication IDs, and do not expect the connection payload to contain one. If no publication is available, skip publishing and tell the user the Shopify Sales Channel publication is not yet provisioned for this connection.
- Publish products with `publishablePublish` using the resolved publication ID.
- Create or update collections as needed.
- Always inspect `userErrors` returned by Shopify Admin mutations and fail loudly when present.

Products are not visible to the Storefront API until they are active and published to a storefront-visible publication. Prefer the Replit-owned Sales Channel publication returned by `publications(first: 20)`; use an existing shop publication like `Online Store` only for Replit-created Vibe/dev stores or after explicit user confirmation on live stores.

Generated setup or seed scripts are orchestration only: they may decide which products to create and which local mapping file to write, but every Shopify Admin request must go through `shopify-admin-api.mjs` or an equivalent OpenInt proxy call with `Connector-Name: shopify-store`. Do not generate scripts that call `https://{shop_domain}/admin/...` directly, use Shopify Admin SDK clients, read Shopify Admin tokens, or duplicate connector provisioning logic.

Product/catalog seeding is a separate step from integration setup. If the user has not provided a product list or explicitly asked for sample products, render an empty storefront state and ask what products they want to add later.

### Rate limits

Shopify Admin GraphQL throttling is cost-based: every response includes `extensions.cost.throttleStatus` with `currentlyAvailable`, `maximumAvailable`, and `restoreRate`. When running batch product or inventory writes through `shopify-admin-api.mjs`, parse `extensions.cost.throttleStatus` from each response and pause (e.g. `sleep ms = (requestedQueryCost - currentlyAvailable) / restoreRate * 1000`) when `currentlyAvailable` drops below the next request's cost. The helper does not throttle automatically. For larger batches (>20 items), prefer Shopify's `bulkOperationRunMutation` over per-item calls. The REST-only `X-Shopify-Shop-Api-Call-Limit` response header does not apply to the Admin GraphQL endpoint this skill uses; only consult it if you fall back to REST.

Shopify Storefront API enforces approximately 60 requests/minute per IP for buyer traffic. For production storefronts, cache product list and product detail responses at the framework level (Next.js `revalidate`, edge cache headers, or in-memory LRU on server actions). Do not call Storefront API from a hot client-side render loop without caching.

## Storefront pattern

Use the Storefront API directly for buyer flows:

- Query products and variants for catalog/product pages.
- Create carts with `cartCreate` using a Storefront `ProductVariant.id` as `merchandiseId`.
- Update cart lines with `cartLinesAdd`, `cartLinesUpdate`, and `cartLinesRemove`.
- Send buyers to Shopify checkout using `cart.checkoutUrl`. When the app is running against a Vibe-created/dev-store preview environment, append `channel=online_store` to the checkout URL before redirecting so Shopify's checkout preview bypasses the dev-store password gate. The connection payload does not flag dev stores; pass this in as a caller-controlled option (e.g. `useDevStorePreview`) based on environment or agent context, and turn it off for live stores.
- If a Storefront API request returns 401 or 403, refetch the Shopify Store connection settings once and retry. If it still fails, stop and report that the OpenInt-provided Storefront token may need to be recreated.

Checkout and payments happen on Shopify. Do not implement custom payment collection unless the user explicitly asks for a different provider.

If `cartCreate` succeeds but opening `cart.checkoutUrl` shows a password-protection page during development, do **not** ask the user to disable the storefront password as the first fix. Keep the Storefront cart flow and add `channel=online_store` to the checkout URL.

If the Storefront API request itself is blocked by dev-store password protection before `cartCreate` returns, that usually means generated code is calling Shopify without the OpenInt-provided Storefront token, or the connection is stale and lacks `storefront_access_token`. Do not ask the user to paste a Storefront token. Use `shopifyStorefrontClient.ts`, which reads the Shopify Store connection settings from OpenInt and retries once on 401/403. If it is still blocked, stop and report that the Shopify Store connection needs a connector-provided `storefront_access_token`; do not pivot to Admin API carts, draft orders, cart permalinks, or disabling the store password.

## Production launch model

Development preview and production selling are different Shopify states:

- During Vibe/dev-store preview, stores are password protected. Use the real Storefront cart and real `cart.checkoutUrl`, then append `channel=online_store` so preview checkout opens without asking the user to disable the password. The connection does not expose a dev-store flag, so this is a caller-controlled option driven by environment/agent context.
- For a live customer store, the merchant must claim/transfer or connect the store, choose a Shopify plan, configure payments, shipping, taxes, markets, and launch the Online Store or sales channel. A live store should use the `checkoutUrl` Shopify returns without appending the dev-store preview parameter.
- Products must be active, in stock, and published to a storefront-visible publication. Resolve the publication ID by querying `publications(first: 20)` and prefer the Replit-owned Sales Channel publication. Fall back to an existing publication such as `Online Store` only for Replit-created Vibe/dev stores, or after explicit merchant confirmation on transferred live stores.
- Orders, payments, fraud checks, taxes, fulfillment, and refunds remain in Shopify. The generated app is the storefront UI and catalog/cart client; OpenInt remains the Admin API boundary for setup and inventory writes.
- If a production checkout is blocked by a password page, explain that the merchant has not launched the Shopify store yet. That is a go-live checklist issue, not a reason to replace Storefront cart checkout with Admin APIs.

## Go Live checklist

Do not transfer the Shopify store during initial build/provisioning. Store transfer is a late "Go Live" action after the user has verified the storefront. A power-user can opt into immediate transfer only if they explicitly say they already have a Shopify merchant account and want transfer now.

When the user asks to go live, walk them through this checklist and use the Shopify Store integration management actions when available:

- Store ownership transfer: the connection payload does not expose a claim link. When the merchant asks to claim or transfer the store, route them to the approved Replit Go Live/transfer surface (Integrations management UI / server-side go-live flow) so it can request a fresh claim URL on demand. From generated app code, treat the claim link as unavailable — do not call an OpenInt connector RPC directly to mint one. If the approved surface is not yet wired up for this flow, tell the merchant their transfer must be initiated through Replit's Go Live tooling and surface `pending_transfer` status if useful; do not collect raw Shopify credentials or claim the connection lacks a claim path. Do not recreate the connection; transfer mutates the existing connection.
- Shopify plan selected: status/deep-link only; merchant must choose and pay for a Shopify plan in Shopify.
- Shopify Payments or third-party gateway KYC: status/deep-link only. Never collect merchant banking, SSN, tax ID, or KYC PII in Replit.
- Payment provider activated: status/deep-link only.
- Shipping zones and rates: status/deep-link only. The Sales Channel App scopes are intentionally scoped down and do not include `write_shipping`; the merchant configures shipping zones, rates, and carrier accounts in Shopify. Agent may suggest reasonable starter shipping defaults in chat (e.g. flat-rate US shipping) but must not apply them through the Admin proxy.
- Taxes configured: status/deep-link only. Do not auto-configure tax rates or registrations; tell the merchant to consult a tax professional.
- Legal policies and store contact info: Agent may draft first-pass policy text with a lawyer-review disclaimer.
- Custom domain: optional status/deep-link only.
- Remove storefront password and launch Online Store: merchant action only. Never auto-disable password protection or auto-launch the store.

Webhook subscriptions for Shopify-side events (order created, order cancelled, inventory changed) are not wired through this connector in v1. Generated apps should pull product, cart, and order data on user-driven refresh or framework cache revalidation (Next.js `revalidate`, server-action revalidation, on-demand revalidation tags) rather than polling Shopify on every render. Do not register Shopify webhooks directly from generated app code; webhook delivery for Shopify Store will be added in a follow-up.

After transfer, the Sales Channel App install can require reauthorization. If OpenInt reports `reauthorization_required`, stop setup writes and tell the user to reconnect Shopify. After reconnect, OpenInt keeps the same connection ID and re-mints Admin/Storefront access. The connection does not carry a dev-store flag, publication ID, or claim link, so there is nothing else to refresh on it; stop appending the dev-store preview parameter once the app is configured for the live storefront.

## Connection assignment conflicts

The `shopify-store` connector is app-scoped. A Shopify Store connection can be assigned to only one Repl/app ID. If OpenInt reports that the connection is already assigned to another Repl, do not claim it belongs to a different Replit account and do not suggest switching payment providers.

When checking whether Shopify is already connected, inspect the connection assignment metadata returned by `listConnections`. If no `shopify-store` connection is assigned to the current Repl/app, say Shopify Store is not connected for this app and ask the user to create a fresh Shopify Store integration. Do not say "Shopify is already connected" just because the user has a Shopify Store connection on another Repl.

Instead:

- Do not try to attach that existing connection ID to the current Repl.
- Create a fresh Shopify Store integration/connection for the current Repl.
- If the old connection lacks `storefront_access_token`, treat it as stale from before the connector was fixed and recreate it.
- If the user believes both Repl IDs are the same app, report the two Repl IDs and ask platform code owners to investigate why the current app is passing a different `repl_id`.

## Rules

- Treat Shopify as the system of record for products, inventory, carts, checkout, and orders.
- Store only minimal local mappings such as handles, product IDs, variant IDs, and cart IDs.
- Use Shopify hosted checkout through `checkoutUrl`.
- Route every Shopify Admin write through OpenInt. Generated app code should never own Admin API authentication.
- Route buyer Storefront API calls directly to Shopify with the connector-provided public Storefront token. Never ask the user to paste a Storefront token.
- Do not implement buyer checkout using Admin API draft orders unless the user explicitly asks for invoice-style manual orders. Draft orders are not the standard storefront cart flow.
- Do not ask the user to disable Shopify dev-store password protection for development preview. Do not try to disable password protection through Admin API or theme mutations.
- Do not query a non-existent Admin GraphQL `storefrontAccessTokens` root field. If Storefront token creation is needed, OpenInt should mint it, preferably with Admin GraphQL `storefrontAccessTokenCreate` plus access-scope verification, falling back to REST `/admin/api/{version}/storefront_access_tokens.json` only when GraphQL is unavailable. Generated apps should read the resulting public token from the connection.
- Do not hardcode Shopify publication IDs, location IDs, product IDs, variant IDs, or shop domains into generated app code. Resolve them from Shopify or from the `shopify-store` connection at setup/runtime.
- Do not duplicate the product catalog in a local database unless the app needs a cache for performance.
- Do not ask the user to manually create products in Shopify; create them through the Admin API.
- If a write requires missing business details, ask for the details once, then proceed.
- If Admin API writes fail because the store was transferred or the app was uninstalled, explain that Shopify needs reauthorization and stop rather than asking for raw tokens.
- If an app-scoped assignment conflict occurs, create a new Shopify Store connection for the current Repl instead of reusing the old connection ID.
- Do not initiate store transfer unless the merchant explicitly chooses Go Live or explicitly opts into immediate transfer.
- Do not recreate the Shopify Store connection as part of transfer or reauthorization. The connection ID must stay stable.
- Do not seed products, collections, or inventory during Shopify integration onboarding. Treat catalog creation as an explicit follow-up task.

## References

- `./references/shopify-admin-api.mjs` - helper for one-off Admin GraphQL calls through the OpenInt proxy.
- `./references/shopifyStorefrontClient.ts` - Storefront API helper for user app code.
- `./references/code-templates.md` - product setup and cart examples.
