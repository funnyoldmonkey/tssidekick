# TS SIDEKICK — MASTER PLAYBOOKS
# Shopify Frontend Troubleshooting & Fix Encyclopedia
# Search this file with: search_playbook("keyword")
# Each section is tagged with [TAGS: ...] for searchable matching.

---

# ═══════════════════════════════════════════════════════════════════
# SECTION 1: SHOPIFY ARCHITECTURE FUNDAMENTALS
# ═══════════════════════════════════════════════════════════════════

## 1.1 Theme File Structure
[TAGS: theme, structure, files, liquid, templates, sections, snippets, assets, layout, architecture]

Shopify themes follow this hierarchy:
```
layout/
  theme.liquid          ← Master wrapper. Every page renders inside {{ content_for_layout }}
  password.liquid       ← Shown when store is password-protected

templates/             ← One per page type. JSON (OS 2.0) or Liquid (vintage)
  product.json         ← Product page template (references sections)
  collection.json      ← Collection page
  index.json           ← Homepage
  cart.json            ← Cart page
  page.json            ← Generic pages
  blog.json            ← Blog listing
  article.json         ← Single blog post
  search.json          ← Search results
  customers/           ← Account pages (login, register, orders)

sections/              ← Reusable content blocks with their own settings
  main-product.liquid  ← The main product section
  header.liquid        ← Site header
  footer.liquid        ← Site footer
  announcement-bar.liquid
  featured-collection.liquid

snippets/              ← Partials included by sections/templates
  card-product.liquid
  price.liquid
  product-variant-picker.liquid

assets/                ← Static files (JS, CSS, images, fonts)
  theme.css / base.css
  global.js
  product-form.js
  cart.js
  cart-drawer.js

config/
  settings_schema.json ← Theme settings definitions
  settings_data.json   ← Current theme settings values

locales/               ← Translation files
  en.default.json
```

Key rules:
- JSON templates (OS 2.0) reference sections by ID. Sections contain blocks.
- Liquid templates (vintage) render content directly. Less flexible.
- `{{ content_for_header }}` in theme.liquid injects Shopify's required scripts (analytics, app scripts, etc.)
- App scripts injected via `content_for_header` run BEFORE theme JS.
- Theme JS files load via `{{ 'filename.js' | asset_url }}` in Liquid.


## 1.2 Page Load & Rendering Order
[TAGS: load order, rendering, script loading, execution order, timing, DOMContentLoaded, performance]

The exact order a Shopify page loads:

1. **HTML parsing begins** — browser reads theme.liquid
2. **`<head>` content** — meta tags, CSS files, preloads
3. **`{{ content_for_header }}`** renders — this injects:
   - Shopify analytics (`trekkie.storefront.load`)
   - Shopify feature detection scripts
   - ALL app scripts (ScriptTag API + theme app extension scripts)
   - Dynamic checkout button scripts
   - Shopify CDN scripts for features (predictive search, etc.)
4. **Theme CSS loads** — `base.css`, `component-*.css`
5. **`<body>` parsing begins** — sections render top to bottom
6. **Inline `<script>` tags in sections** — execute as parser encounters them
7. **Deferred theme JS** — `product-form.js`, `cart.js`, etc. (usually `defer` or at bottom)
8. **`DOMContentLoaded` fires** — custom elements upgrade, event listeners attach
9. **`load` event fires** — images loaded, fonts loaded
10. **App scripts that waited for DOMContentLoaded** — these run AFTER theme JS

CRITICAL TIMING ISSUES:
- App scripts from `content_for_header` may run BEFORE theme custom elements are defined
- If an app looks for `product-form` custom element before `product-form.js` loads → fails silently
- If two apps both monkey-patch `window.fetch` → last one wins, first one breaks
- Scripts with `defer` attribute execute in order they appear in DOM
- Scripts with `async` attribute execute whenever they finish downloading (unpredictable order)


## 1.3 Custom Elements (Web Components) in Shopify Themes
[TAGS: custom elements, web components, product-form, variant-selects, quantity-input, cart-drawer, cart-notification, details-disclosure, modal-dialog, deferred-media, slider-component, sticky-header]

Shopify's Dawn theme (and all themes based on it) uses Web Components heavily. These are HTML Custom Elements — NOT Shadow DOM.

Key custom elements and what they do:

```
product-form           ← Wraps the add-to-cart form. Handles AJAX submission.
variant-selects        ← Dropdown variant pickers. Fires 'change' events.
variant-radios         ← Radio button variant pickers.
quantity-input         ← +/- quantity buttons with input field.
cart-drawer            ← Slide-out cart drawer. Listens for cart:refresh events.
cart-notification      ← "Added to cart" popup notification.
cart-items             ← Cart line items container.
details-disclosure     ← Expandable content (FAQ, filters).
modal-dialog           ← Product media modal (image zoom).
deferred-media         ← Lazy-loaded video/3D model.
slider-component       ← Image carousel/slider.
slideshow-component    ← Homepage slideshow.
sticky-header          ← Header that sticks on scroll.
predictive-search      ← Search-as-you-type.
pickup-availability    ← Store pickup availability checker.
product-info           ← Product information wrapper (newer themes).
media-gallery          ← Product image gallery (newer themes).
price-per-item         ← Dynamic price display.
bulk-add               ← Quick add from collection.
facet-filters-form     ← Collection filtering.
```

How they work:
```javascript
// Definition pattern (in product-form.js):
if (!customElements.get('product-form')) {
  customElements.define('product-form', class extends HTMLElement {
    constructor() {
      super();
      this.form = this.querySelector('form');
      this.form.addEventListener('submit', this.onSubmitHandler.bind(this));
    }
    
    onSubmitHandler(evt) {
      evt.preventDefault();
      // AJAX cart add via fetch()
      const formData = new FormData(this.form);
      fetch(window.Shopify.routes.root + 'cart/add.js', {
        method: 'POST',
        body: formData,
      })
      .then(response => response.json())
      .then(data => {
        // Update cart drawer or redirect
      });
    }
  });
}
```

WHY THIS MATTERS FOR TROUBLESHOOTING:
- If `product-form.js` fails to load → `product-form` tag exists but has NO behavior
- If an app replaces the form's submit handler → the custom element's handler is bypassed
- If `variant-selects` or `variant-radios` fail → variant change events never fire → wrong variant in cart
- The `quantity-input` buttons are INSIDE the custom element — if the element isn't upgraded, buttons do nothing
- Custom elements are NOT re-initialized after AJAX content replacement unless explicitly handled


## 1.4 App Integration Architecture
[TAGS: app, integration, script tag, theme app extension, app block, app embed, content_for_header, third party, injection]

Apps inject code into Shopify stores via two mechanisms:

### ScriptTag API (Legacy)
- App registers a script URL with Shopify
- Shopify injects it via `{{ content_for_header }}` in theme.liquid
- Script loads on EVERY page (unless filtered by the app)
- Runs in the MAIN world (same as theme JS)
- Can access/modify any DOM element, override any JS function
- Cannot be disabled by merchant without uninstalling the app
- Many apps still use this even in 2026

### Theme App Extensions (Modern — OS 2.0+)
Two sub-types:

**App Blocks:**
- Rendered inline within sections (like any other block)
- Merchant adds them via Theme Customizer → Section → Add Block → Apps
- Only work in OS 2.0 themes with JSON templates
- Rendered server-side as Liquid → becomes part of the section HTML
- Can include their own JS and CSS
- Position is controllable by merchant

**App Embeds:**
- Floating/overlay elements (chat widgets, announcement bars, analytics)
- Enabled via Theme Customizer → Theme Settings → App Embeds toggle
- NOT tied to any specific section or page position
- Can inject JS/CSS globally
- Default: DEACTIVATED after install — merchant must enable
- This is the #1 reason "app doesn't show" — merchant forgot to enable the embed

HOW TO IDENTIFY WHICH METHOD AN APP USES:
- ScriptTag: Look for `<script src="https://cdn.shopify.com/extensions/...">` or `<script src="https://some-app-domain.com/...">` in `<head>` (injected by content_for_header)
- App Block: Look for `<div class="shopify-block" data-block-type="shopify://apps/...">` in the section HTML
- App Embed: Look for `<div id="shopify-block-..." data-block-type="shopify://apps/...">` usually at the end of `<body>`

COMMON APP CONFLICT PATTERNS:
1. Two apps both override `window.fetch` → one breaks the other
2. App modifies product form HTML → theme's product-form custom element breaks
3. App injects CSS that conflicts with theme CSS → layout breaks
4. App's MutationObserver fights with another app's MutationObserver → infinite loop, page freezes
5. App script runs before custom element is defined → querySelector returns null → silent failure
6. Uninstalled app left residual code in theme files → errors on every page


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 2: SHOPIFY AJAX & API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

## 2.1 Cart API (Ajax)
[TAGS: cart, ajax, api, add to cart, update cart, cart.js, cart/add.js, cart/update.js, cart/change.js, cart/clear.js, endpoint, fetch, POST, GET]

All cart endpoints are relative to the store's root. Use `window.Shopify.routes.root` as base.

### POST /cart/add.js
Adds items to cart.
```
Request body (JSON):
{
  "items": [
    {
      "id": 794864229,           // variant ID (REQUIRED)
      "quantity": 1,             // quantity (REQUIRED)
      "selling_plan": 123456,    // optional: subscription selling plan ID
      "properties": {            // optional: line item properties
        "_gift_wrap": "true"
      }
    }
  ]
}

Success response (200):
{
  "items": [
    {
      "id": 794864229,
      "quantity": 1,
      "variant_id": 794864229,
      "title": "Product Title - Variant Title",
      "price": 1999,            // price in cents
      "line_price": 1999,
      "sku": "SKU-123",
      "grams": 500,
      "vendor": "Vendor Name",
      "product_id": 788032119674292922,
      "image": "https://cdn.shopify.com/...",
      "url": "/products/handle?variant=794864229"
    }
  ]
}

Error response (422):
{
  "status": 422,
  "message": "Cart Error",
  "description": "variant_id is required but was empty or invalid"
}
```

### POST /cart/update.js
Updates quantities, cart note, or cart attributes.
```
Request body:
{
  "updates": {
    "794864229": 3,     // variant_id: new_quantity
    "794864230": 0      // set to 0 to remove
  }
}
// OR array format:
{
  "updates": [3, 0]    // quantities by line item index
}
// For cart note:
{
  "note": "Please gift wrap"
}
// For cart attributes:
{
  "attributes": {
    "gift_note": "Happy Birthday"
  }
}

Success response: Full cart object (same as GET /cart.js)
```

### POST /cart/change.js
Changes a single line item. More precise than update.js.
```
Request body:
{
  "id": "794864229:abc123",  // line item key (variant_id:properties_hash)
  "quantity": 2
}
// OR by line index:
{
  "line": 1,          // 1-indexed line number
  "quantity": 2
}

Note: "id" here is the LINE ITEM KEY, not just the variant ID.
The line item key is available in the cart object as item.key.
```

### POST /cart/clear.js
Empties the entire cart.
```
Request body: (empty or {})
Response: Empty cart object
```

### GET /cart.js
Returns the current cart as JSON.
```
Response:
{
  "token": "abc123...",
  "note": "",
  "attributes": {},
  "original_total_price": 3998,
  "total_price": 3998,
  "total_discount": 0,
  "total_weight": 1000.0,
  "item_count": 2,
  "items": [
    {
      "id": 794864229,
      "quantity": 1,
      "variant_id": 794864229,
      "key": "794864229:abc123",
      "title": "Product - Variant",
      "price": 1999,
      "original_price": 1999,
      "discounted_price": 1999,
      "line_price": 1999,
      "original_line_price": 1999,
      "total_discount": 0,
      "discounts": [],
      "sku": "SKU-123",
      "grams": 500,
      "vendor": "Vendor",
      "taxable": true,
      "product_id": 788032119674292922,
      "product_has_only_default_variant": false,
      "gift_card": false,
      "url": "/products/handle?variant=794864229",
      "featured_image": { "url": "...", "alt": "..." },
      "image": "https://cdn.shopify.com/...",
      "handle": "product-handle",
      "requires_shipping": true,
      "product_type": "Type",
      "product_title": "Product Title",
      "product_description": "...",
      "variant_title": "Small / Red",
      "variant_options": ["Small", "Red"],
      "options_with_values": [
        { "name": "Size", "value": "Small" },
        { "name": "Color", "value": "Red" }
      ],
      "line_level_discount_allocations": [],
      "line_level_total_discount": 0,
      "selling_plan_allocation": null,
      "properties": {}
    }
  ],
  "requires_shipping": true,
  "currency": "USD",
  "items_subtotal_price": 3998,
  "cart_level_discount_applications": []
}
```

TROUBLESHOOTING CART API:
- If /cart/add.js returns 422 with "variant_id" error → the form is sending empty or invalid variant ID
- If /cart/add.js returns 422 with "product is not available" → product is draft, or not on Online Store channel
- If /cart/add.js silently fails → check if window.fetch has been monkey-patched (see Section 5)
- If cart updates but UI doesn't reflect → cart drawer/notification not listening for events
- Always check `Content-Type: application/json` header on POST requests
- Some themes use FormData instead of JSON — both are valid


## 2.2 Product API (Ajax)
[TAGS: product, api, product.json, product.js, variants, images, options, handle, endpoint]

### GET /products/{handle}.js
Returns product as JavaScript-friendly JSON (no wrapper object).
```
Response:
{
  "id": 788032119674292922,
  "title": "The 3P Fulfilled Snowboard",
  "handle": "the-3p-fulfilled-snowboard",
  "description": "<p>HTML description...</p>",
  "published_at": "2024-01-15T...",
  "created_at": "2024-01-15T...",
  "vendor": "Snowboard Vendor",
  "type": "Snowboard",
  "tags": ["preorder-enabled", "winter", "sports"],
  "price": 1999,
  "price_min": 1999,
  "price_max": 2999,
  "available": true,
  "price_varies": true,
  "compare_at_price": 2499,
  "compare_at_price_min": 2499,
  "compare_at_price_max": 3499,
  "compare_at_price_varies": true,
  "variants": [
    {
      "id": 43212284067903,
      "title": "Small",
      "option1": "Small",
      "option2": null,
      "option3": null,
      "sku": "SNOW-SM",
      "requires_shipping": true,
      "taxable": true,
      "featured_image": null,
      "available": true,
      "name": "The 3P Fulfilled Snowboard - Small",
      "public_title": "Small",
      "options": ["Small"],
      "price": 1999,
      "weight": 5000,
      "compare_at_price": 2499,
      "inventory_management": "shopify",
      "barcode": "",
      "inventory_policy": "continue",
      "inventory_quantity": 0,
      "requires_selling_plan": false,
      "selling_plan_allocations": []
    }
  ],
  "images": [
    "//cdn.shopify.com/s/files/1/xxxx/products/snowboard.png"
  ],
  "featured_image": "//cdn.shopify.com/s/files/1/xxxx/products/snowboard.png",
  "options": [
    {
      "name": "Size",
      "position": 1,
      "values": ["Small", "Medium", "Large"]
    }
  ],
  "url": "/products/the-3p-fulfilled-snowboard",
  "media": [
    {
      "alt": null,
      "id": 123456,
      "position": 1,
      "preview_image": { "aspect_ratio": 1.0, "height": 1000, "width": 1000, "src": "..." },
      "aspect_ratio": 1.0,
      "height": 1000,
      "media_type": "image",
      "src": "...",
      "width": 1000
    }
  ],
  "requires_selling_plan": false,
  "selling_plan_groups": []
}
```

### GET /products/{handle}.json
Same data but wrapped: `{ "product": { ... } }`

KEY FIELDS FOR TROUBLESHOOTING:
- `available` — is any variant purchasable?
- `variants[].available` — is THIS specific variant purchasable?
- `variants[].inventory_policy` — "deny" (stop selling at 0) or "continue" (allow overselling/preorder)
- `variants[].inventory_quantity` — current stock level
- `variants[].inventory_management` — "shopify" (tracked) or null (untracked/always available)
- `tags` — apps often use tags like "preorder-enabled", "subscription", "bundle"
- `requires_selling_plan` — if true, MUST have a selling plan selected to add to cart
- `selling_plan_groups` — subscription options attached to this product
- `options` — variant option names and values (Size, Color, etc.)

HOW TO GET PRODUCT JSON FROM ANY PRODUCT PAGE:
```javascript
// Method 1: Fetch from URL
const handle = window.location.pathname.split('/products/')[1]?.split('?')[0];
const product = await fetch(`/products/${handle}.js`).then(r => r.json());

// Method 2: From meta tag (some themes)
const productMeta = document.querySelector('meta[property="og:type"][content="product"]');

// Method 3: From Liquid-generated global (some themes)
const product = window.product || window.ShopifyAnalytics?.meta?.product;

// Method 4: From section data attribute
const section = document.querySelector('[data-product-json]');
const product = JSON.parse(section.textContent);

// Method 5: From script tag with type application/json
const scriptTag = document.querySelector('script[data-product-json], script#product-json');
const product = JSON.parse(scriptTag.textContent);
```


## 2.3 Section Rendering API
[TAGS: section rendering, ajax, dynamic section, refresh, partial page, section_id, sections parameter]

Fetch fresh HTML for specific sections without full page reload.

### Single section
```
GET /products/handle?section_id=main-product
Response: Raw HTML of that section
```

### Multiple sections (up to 5)
```
GET /products/handle?sections=main-product,cart-drawer,header
Response (JSON):
{
  "main-product": "<div id=\"shopify-section-...\" class=\"shopify-section\">...</div>",
  "cart-drawer": "<div id=\"shopify-section-...\" class=\"shopify-section\">...</div>",
  "header": "<div id=\"shopify-section-...\" class=\"shopify-section\">...</div>"
}
```

### Dynamic section IDs
In JSON templates, sections have dynamic IDs like `template--12345__main-product`.
To get the correct ID:
```javascript
const sectionId = document.querySelector('.shopify-section')?.id?.replace('shopify-section-', '');
```

COMMON USES:
- Cart drawer updates after add-to-cart
- Product section refresh after variant change
- Collection page filtering (faceted navigation)
- Predictive search results

TROUBLESHOOTING:
- If section rendering returns 404 → section ID doesn't exist in theme
- If section rendering returns stale data → check caching (CDN or browser cache)
- If section doesn't re-render correctly → custom elements in new HTML aren't initialized
  → Must call `customElements.upgrade(newElement)` or the theme's initialization function


## 2.4 Other Useful Endpoints
[TAGS: endpoints, search, recommendations, collections, api, predictive search, product recommendations]

```
GET /search/suggest.json?q=term&resources[type]=product
  → Predictive search results (products, collections, articles, pages)

GET /recommendations/products.json?product_id=123456&limit=10
  → Product recommendations (complementary, related)

GET /collections/{handle}/products.json
  → All products in a collection (paginated, 250 max per page)

GET /collections/{handle}/products.json?sort_by=price-ascending
  → Sorted collection products

GET /cart/shipping_rates.json?shipping_address[zip]=10001&shipping_address[country]=US
  → Shipping rate estimates (requires cart to have items)
```

## 2.5 Shopify Global JavaScript Objects
[TAGS: Shopify, window, global, routes, locale, currency, meta, analytics, ShopifyAnalytics, Shopify.routes]

Available on every Shopify page:
```javascript
window.Shopify = {
  shop: "store-name.myshopify.com",
  locale: "en",
  currency: {
    active: "USD",
    rate: "1.0"
  },
  country: "US",
  theme: {
    name: "Dawn",
    id: 123456789,
    theme_store_id: 887,          // null for custom themes
    role: "main",                 // "main" or "unpublished"
    handle: "dawn"
  },
  routes: {
    root: "/"                      // locale prefix: "/en/" for multi-language
  },
  cdnHost: "cdn.shopify.com",
  modules: true,
  PaymentButton: { ... },
  autoloadFeatures: { ... }
};

window.ShopifyAnalytics = {
  meta: {
    product: {                     // Only on product pages
      id: 123456,
      gid: "gid://shopify/Product/123456",
      vendor: "Vendor",
      type: "Type",
      variants: [{ id: 789, ... }]
    },
    page: { pageType: "product", resourceType: "product", resourceId: 123456 }
  }
};

// Useful for checking page type:
window.ShopifyAnalytics.meta.page.pageType
// Values: "home", "product", "collection", "cart", "page", "blog", "article", "search", "customers/login", etc.
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 3: PRODUCT PAGE ANATOMY & FORM STRUCTURE
# ═══════════════════════════════════════════════════════════════════

## 3.1 Standard Product Form Structure (Dawn/OS 2.0)
[TAGS: product form, form structure, add to cart, variant selector, quantity, submit button, form action, input name id, product-form, variant-selects, hidden input]

The standard Shopify product form that apps and themes expect:

```html
<product-form class="product-form" data-hide-errors="false">
  <div class="product-form__error-message-wrapper" role="alert" hidden>
    <span class="product-form__error-message"></span>
  </div>
  
  <form method="post" action="/cart/add" 
        id="product-form-template--12345__main"
        accept-charset="UTF-8" 
        class="form" 
        enctype="multipart/form-data"
        novalidate="novalidate"
        data-type="add-to-cart-form">
    
    <input type="hidden" name="form_type" value="product">
    <input type="hidden" name="utf8" value="✓">
    
    <!-- VARIANT SELECTOR (one of these patterns): -->
    
    <!-- Pattern A: Select dropdown -->
    <variant-selects class="no-js-hidden" 
                     data-section="template--12345__main"
                     data-url="/products/handle">
      <select name="id" class="select__select" 
              id="Variants-template--12345__main"
              form="product-form-template--12345__main">
        <option value="43212284067903" selected>Small - $19.99</option>
        <option value="43212284067904">Medium - $24.99</option>
        <option value="43212284067905">Large - $29.99</option>
      </select>
    </variant-selects>
    
    <!-- Pattern B: Radio buttons -->
    <variant-radios class="no-js-hidden"
                    data-section="template--12345__main"
                    data-url="/products/handle">
      <fieldset class="js product-form__input">
        <legend class="form__label">Size</legend>
        <input type="radio" name="Size" value="Small" checked 
               id="template--12345__main-Size-0"
               form="product-form-template--12345__main">
        <label for="template--12345__main-Size-0">Small</label>
        <!-- ... more radios ... -->
      </fieldset>
      <!-- Hidden input gets updated by JS when radio changes -->
      <input type="hidden" name="id" value="43212284067903"
             form="product-form-template--12345__main">
    </variant-radios>
    
    <!-- Pattern C: Single variant (no selector shown) -->
    <input type="hidden" name="id" value="43212284067903"
           form="product-form-template--12345__main">
    
    <!-- QUANTITY INPUT -->
    <quantity-input class="quantity">
      <button class="quantity__button" name="minus" type="button">
        <span>−</span>
      </button>
      <input class="quantity__input" type="number" name="quantity"
             id="Quantity-template--12345__main" 
             min="1" value="1" form="product-form-template--12345__main">
      <button class="quantity__button" name="plus" type="button">
        <span>+</span>
      </button>
    </quantity-input>
    
    <!-- SUBMIT BUTTON -->
    <button type="submit" name="add" class="product-form__submit button button--full-width"
            id="ProductSubmitButton-template--12345__main"
            aria-label="Add to cart">
      <span>Add to cart</span>
    </button>
    
    <!-- DYNAMIC CHECKOUT (Buy Now / Apple Pay / Shop Pay) -->
    <div class="shopify-payment-button" data-has-selling-plan="false">
      <!-- Shopify injects dynamic checkout buttons here -->
    </div>
  </form>
</product-form>
```

CRITICAL ELEMENTS APPS LOOK FOR:
- `form[action*="/cart/add"]` — the form itself
- `input[name="id"]` or `select[name="id"]` — variant ID (MOST IMPORTANT)
- `button[type="submit"]` or `button[name="add"]` or `.product-form__submit` — the add-to-cart button
- `input[name="quantity"]` — quantity field
- `input[name="selling_plan"]` — subscription plan selector
- `[data-add-to-cart]` — some apps use this data attribute

IF ANY OF THESE ARE MISSING, APPS WILL BREAK.


## 3.2 Variant Selection Mechanism
[TAGS: variant, selection, variant change, option change, variant ID, URL parameter, variant event, current variant, selected variant]

How variant selection works in Dawn:

1. User clicks a size/color option
2. `variant-selects` or `variant-radios` custom element catches the change event
3. Element finds the matching variant from the product JSON
4. Hidden `input[name="id"]` is updated with the new variant ID
5. URL is updated with `?variant=XXXXX` parameter
6. Section Rendering API is called to refresh the product section with new variant data
7. Price, availability, images update accordingly

```javascript
// How themes typically store product data for variant lookup:
// In the section HTML, there's usually a script tag:
<script type="application/json" id="product-json-template--12345__main">
  {
    "id": 788032119674292922,
    "variants": [
      { "id": 43212284067903, "available": true, "price": 1999, ... },
      { "id": 43212284067904, "available": false, "price": 2499, ... }
    ]
  }
</script>
```

HOW TO GET THE CURRENTLY SELECTED VARIANT:
```javascript
// Method 1: From URL
const params = new URLSearchParams(window.location.search);
const variantId = params.get('variant');

// Method 2: From hidden input
const variantInput = document.querySelector('input[name="id"], select[name="id"]');
const variantId = variantInput?.value;

// Method 3: From product form data attribute
const form = document.querySelector('product-form form, form[action*="/cart/add"]');
const formData = new FormData(form);
const variantId = formData.get('id');

// Method 4: From Shopify Analytics (always accurate)
const variantId = window.ShopifyAnalytics?.meta?.selectedVariantId;

// Method 5: From product JSON + URL
const handle = window.location.pathname.split('/products/')[1]?.split('?')[0];
const product = await fetch(`/products/${handle}.js`).then(r => r.json());
const selectedId = new URLSearchParams(window.location.search).get('variant');
const variant = product.variants.find(v => v.id == selectedId) || product.variants[0];
```

COMMON VARIANT ISSUES:
- Variant input exists but value is empty → app wiped it, or theme JS didn't initialize
- Variant input doesn't exist → theme uses a different pattern (custom JS, Preact/React, etc.)
- URL has ?variant= but input doesn't match → desync between URL and form state
- All variants show "unavailable" → inventory_policy is "deny" and quantity is 0
- Variant shows wrong price → variant data not refreshed after selection


## 3.3 Price Display Elements
[TAGS: price, display, price-item, compare at price, sale price, regular price, money format, currency, hidden price, invisible price]

Standard price HTML structure in Dawn:

```html
<div class="price price--on-sale price--show-badge" 
     id="price-template--12345__main">
  
  <div class="price__container">
    <!-- Regular price (struck through when on sale) -->
    <div class="price__regular">
      <span class="visually-hidden">Regular price</span>
      <span class="price-item price-item--regular">$24.99</span>
    </div>
    
    <!-- Sale price -->
    <div class="price__sale">
      <span class="visually-hidden">Regular price</span>
      <span>
        <s class="price-item price-item--regular">$24.99</s>
      </span>
      <span class="visually-hidden">Sale price</span>
      <span class="price-item price-item--sale price-item--last">$19.99</span>
    </div>
  </div>
  
  <!-- Sale badge -->
  <span class="badge price__badge-sale color-scheme-4">Sale</span>
  
  <!-- Unit price (per 100ml, per kg, etc.) -->
  <div class="price__unit-price">
    <span class="visually-hidden">Unit price</span>
    <span class="price-item price-item--last">$2.00</span>
    <span>/</span>
    <span>100ml</span>
  </div>
</div>
```

CSS CLASSES THAT CONTROL PRICE VISIBILITY:
- `.price--on-sale` — shows sale price, hides regular price section
- `.price--sold-out` — may gray out or show "Sold out" instead of price
- `.price--show-badge` — shows the "Sale" badge
- `.price-item--regular` — the compare-at (original) price
- `.price-item--sale` — the current (discounted) price
- `.price-item--last` — the final displayed price

PRICE FORMATTING:
Shopify uses money filters in Liquid. The format comes from the store's settings.
Common JavaScript money formatting:
```javascript
// Shopify's built-in formatter (if available):
Shopify.formatMoney(priceInCents, moneyFormat);

// The money format string is typically:
// "${{amount}}"         → $19.99
// "${{amount_no_decimals}}" → $19
// "${{amount_with_comma_separator}}" → $19,99
// "€{{amount_with_apostrophe_separator}}" → €19'99

// You can find the format in:
window.Shopify.money_format   // Not always available
// Or from a meta/script tag the theme puts in
```

TROUBLESHOOTING PRICE ISSUES:
- Price shows $0.00 → variant has price 0, or price not populated in Liquid
- Price shows wrong currency → multi-currency not configured, or JS formatter wrong
- Price doesn't update on variant change → Section Rendering API not called, or event listener missing
- Price invisible but element exists → CSS hiding it (see Section 5 for detection)


## 3.4 Product Media (Images, Video, 3D)
[TAGS: product media, images, gallery, image carousel, video, 3d model, media gallery, srcset, responsive image, lazy loading, deferred media]

```html
<media-gallery id="MediaGallery-template--12345__main" 
               class="product__media-gallery">
  <div class="product__media-list">
    <div class="product__media-item" data-media-id="123456">
      <img src="//cdn.shopify.com/s/.../product_600x.jpg"
           srcset="//cdn.shopify.com/s/.../product_200x.jpg 200w,
                   //cdn.shopify.com/s/.../product_400x.jpg 400w,
                   //cdn.shopify.com/s/.../product_600x.jpg 600w,
                   //cdn.shopify.com/s/.../product_800x.jpg 800w"
           sizes="(min-width: 750px) 50vw, 100vw"
           loading="lazy"
           width="600"
           height="600"
           alt="Product image">
    </div>
    
    <!-- Video (lazy loaded) -->
    <div class="product__media-item" data-media-id="789">
      <deferred-media class="deferred-media">
        <button class="deferred-media__poster">
          <img src="video-poster.jpg" alt="Play video">
        </button>
        <template>
          <video src="video.mp4" controls></video>
        </template>
      </deferred-media>
    </div>
  </div>
  
  <!-- Thumbnails -->
  <slider-component class="thumbnail-list">
    <button class="thumbnail" data-target="123456">
      <img src="thumb_100x.jpg" alt="">
    </button>
  </slider-component>
</media-gallery>
```

IMAGE URL MANIPULATION ON SHOPIFY CDN:
```
Original: //cdn.shopify.com/s/files/1/xxxx/products/photo.jpg
Resized:  //cdn.shopify.com/s/files/1/xxxx/products/photo_300x300.jpg
Cropped:  //cdn.shopify.com/s/files/1/xxxx/products/photo_300x300_crop_center.jpg

Size suffixes: _100x, _200x, _300x, _400x, _600x, _800x, _1000x, _1200x
Crop modes: _crop_center, _crop_top, _crop_bottom, _crop_left, _crop_right

// In JavaScript, to resize an image URL:
function getSizedImageUrl(url, size) {
  return url.replace(/\.(jpg|jpeg|png|gif|webp)/, `_${size}.$1`);
}
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 4: SYMPTOM → ROOT CAUSE → FIX RECIPES
# ═══════════════════════════════════════════════════════════════════

## 4.1 Add to Cart Button Broken
[TAGS: add to cart, button, disabled, unavailable, broken, not working, cannot add, cart button, submit button, grayed out, greyed out]

### Symptom: Button says "Unavailable" or is grayed out
POSSIBLE CAUSES (check in order):
1. **All variants sold out** — Check `product.available` and each `variant.available`
   - Fix: If inventory_policy is "continue", button should still work. Theme bug.
2. **Variant input empty** — `input[name="id"]` has no value
   - Fix: Set value from product JSON or URL parameter
3. **Button has disabled attribute** — Something added `disabled` to the button
   - Fix: `btn.removeAttribute('disabled'); btn.removeAttribute('aria-disabled');`
4. **Rogue app sabotage** — Look for `data-sabotage-*`, `data-guard-*`, or suspicious tooltips
   - Fix: See Section 4.20 (Rogue App / Sabotage Detection)
5. **CSS hiding the button** — `opacity:0`, `z-index:-999`, `clip-path`, `visibility:hidden`
   - Fix: See Section 5 (CSS Override Techniques)
6. **Product form missing** — No `form[action*="/cart/add"]` in DOM
   - Fix: Theme uses custom JS cart add. Check for fetch calls to /cart/add.js

### Symptom: Button visible but clicking does nothing
POSSIBLE CAUSES:
1. **product-form custom element not initialized** — JS file failed to load
   - Search DOM for `<product-form`. If no matching JS file loaded → inject cart add handler
2. **fetch() intercepted** — An app/script is blocking /cart/add calls
   - Test: `window.fetch.toString()` — if it doesn't contain "native code", it's patched
   - Fix: Restore from iframe (see Section 4.13)
3. **Form submit event intercepted** — Capture-phase event listener blocking
   - Fix: Clone the form to strip listeners, or find and remove the interceptor
4. **Missing variant ID** — Form submits but variant ID is blank → 422 error
   - Check network tab for failed /cart/add requests
5. **JavaScript error** — Check console for errors during click
   - Common: "Cannot read properties of undefined" → null reference in product form JS

### Quick diagnostic injection:
```javascript
// Inject this to test cart add functionality directly:
(function() {
  const variantInput = document.querySelector('input[name="id"], select[name="id"]');
  const variantId = variantInput?.value;
  console.log('[TS-DIAG] Variant ID:', variantId);
  console.log('[TS-DIAG] fetch is native:', window.fetch.toString().includes('native code'));
  console.log('[TS-DIAG] Forms:', document.querySelectorAll('form[action*="/cart/add"]').length);
  console.log('[TS-DIAG] Submit buttons:', document.querySelectorAll('button[type="submit"], button[name="add"], .product-form__submit').length);
  
  const btn = document.querySelector('button[name="add"], .product-form__submit, button[type="submit"]');
  if (btn) {
    console.log('[TS-DIAG] Button disabled:', btn.disabled);
    console.log('[TS-DIAG] Button aria-disabled:', btn.getAttribute('aria-disabled'));
    console.log('[TS-DIAG] Button computed opacity:', getComputedStyle(btn).opacity);
    console.log('[TS-DIAG] Button computed z-index:', getComputedStyle(btn).zIndex);
    console.log('[TS-DIAG] Button computed pointer-events:', getComputedStyle(btn).pointerEvents);
  }
})();
```


## 4.2 Prices Not Showing / Invisible
[TAGS: price, invisible, hidden, not showing, transparent, zero size, font size 0, price missing, price blank, price disappeared]

### Symptom: Price area exists but text is invisible
COMMON CSS TRICKS THAT HIDE PRICES:
```css
/* Transparent text */
color: transparent !important;
-webkit-text-fill-color: transparent !important;

/* Zero-size text */
font-size: 0px !important;
letter-spacing: -9999px !important;

/* Element hidden */
opacity: 0 !important;
visibility: hidden !important;
display: none !important;

/* Pushed off-screen */
position: fixed; left: -9999px;
transform: translateX(-9999px);
clip-path: inset(50%);
```

### Diagnostic injection:
```javascript
// Find all price elements and check their computed styles:
(function() {
  const priceEls = document.querySelectorAll('.price-item, [class*="price"], .money');
  priceEls.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const issues = [];
    if (cs.color === 'rgba(0, 0, 0, 0)' || cs.color === 'transparent') issues.push('color:transparent');
    if (cs.webkitTextFillColor === 'transparent') issues.push('text-fill-color:transparent');
    if (parseFloat(cs.fontSize) === 0) issues.push('font-size:0');
    if (parseFloat(cs.opacity) === 0) issues.push('opacity:0');
    if (cs.visibility === 'hidden') issues.push('visibility:hidden');
    if (cs.display === 'none') issues.push('display:none');
    if (issues.length > 0) {
      console.log(`[TS-DIAG] Price #${i} "${el.textContent.trim()}" HIDDEN BY: ${issues.join(', ')}`);
    }
  });
})();
```

### Fix recipe — Counter-CSS injection:
```css
/* Nuclear override for all common price hiding techniques */
.price-item,
.price-item--regular,
.price-item--sale,
.price-item--last,
.money,
[class*="price-item"] {
  color: inherit !important;
  -webkit-text-fill-color: inherit !important;
  font-size: inherit !important;
  letter-spacing: normal !important;
  opacity: 1 !important;
  visibility: visible !important;
  display: inline !important;
  position: static !important;
  clip-path: none !important;
  transform: none !important;
  text-shadow: none !important;
  width: auto !important;
  height: auto !important;
  overflow: visible !important;
  user-select: auto !important;
}
```

NOTE: Using `inherit` instead of a specific value lets the element pick up the theme's intended color rather than forcing a hardcoded color.


## 4.3 Variant Dropdown Corrupted / Garbled Text
[TAGS: variant, dropdown, corrupted, garbled, error text, Err_0, variant_corrupt, option text, select option, broken dropdown]

### Symptom: Variant options show text like "Err_0 [variant_corrupt]"
ROOT CAUSE: A script replaced the option text content. The original values are usually preserved in data attributes.

### Fix:
```javascript
// Restore variant option labels from data attributes or product JSON:
(function() {
  // Try data attribute restoration first
  document.querySelectorAll('select[name="id"] option, variant-selects select option').forEach(opt => {
    if (opt.dataset.originalLabel) {
      opt.textContent = opt.dataset.originalLabel;
    }
  });
  
  // If no data attributes, rebuild from product JSON:
  const handle = window.location.pathname.split('/products/')[1]?.split('?')[0];
  if (handle) {
    fetch('/products/' + handle + '.js')
      .then(r => r.json())
      .then(product => {
        document.querySelectorAll('select[name="id"] option').forEach(opt => {
          const variant = product.variants.find(v => v.id == opt.value);
          if (variant) {
            opt.textContent = variant.title + (variant.available ? '' : ' - Sold out');
          }
        });
      });
  }
})();
```


## 4.4 Product Images Blurry or Corrupted
[TAGS: image, blurry, corrupted, filter, blur, saturate, grayscale, product image, media, gallery, opacity]

### Symptom: Product images look washed out, blurry, or desaturated
ROOT CAUSE: CSS `filter` property applied to media elements.

### Diagnostic:
```javascript
(function() {
  const mediaEls = document.querySelectorAll('.product__media-item, .product__media-wrapper, .product__media-list, .product-media-container, img[srcset]');
  mediaEls.forEach((el, i) => {
    const cs = getComputedStyle(el);
    if (cs.filter !== 'none') console.log(`[TS-DIAG] Media #${i} filter: ${cs.filter}`);
    if (parseFloat(cs.opacity) < 1) console.log(`[TS-DIAG] Media #${i} opacity: ${cs.opacity}`);
  });
})();
```

### Fix:
```css
.product__media-list,
.product__media-item,
.product-media-container,
.product__media-wrapper,
.product__media-list img,
.product__media-item img {
  filter: none !important;
  opacity: 1 !important;
  -webkit-filter: none !important;
}
```


## 4.5 Layout Shifted / Spacing Wrong
[TAGS: layout, shifted, spacing, margin, padding, position, pushed down, offset, misaligned, gap, displaced]

### Symptom: Product content pushed down, weird gaps, elements misaligned
ROOT CAUSE: CSS injecting extra margin, padding, position offsets, or transform.

### Diagnostic:
```javascript
(function() {
  const els = document.querySelectorAll('.product__info-wrapper, .product__info-container, .product, main > .shopify-section');
  els.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const issues = [];
    if (parseInt(cs.marginTop) > 50) issues.push(`margin-top:${cs.marginTop}`);
    if (parseInt(cs.top) > 20) issues.push(`top:${cs.top}`);
    if (cs.position === 'relative' && parseInt(cs.top) !== 0) issues.push(`position:relative;top:${cs.top}`);
    if (cs.transform !== 'none') issues.push(`transform:${cs.transform}`);
    if (parseInt(cs.maxHeight) < 500 && parseInt(cs.maxHeight) > 0) issues.push(`max-height:${cs.maxHeight}`);
    if (issues.length) console.log(`[TS-DIAG] Layout ${el.className.split(' ')[0]} #${i}: ${issues.join(', ')}`);
  });
})();
```

### Fix:
```css
.product__info-wrapper,
.product__info-container {
  position: static !important;
  top: auto !important;
  margin-top: 0 !important;
  max-height: none !important;
  overflow: visible !important;
  transform: none !important;
}

.section-header ~ .shopify-section:first-of-type {
  margin-top: 0 !important;
}
```


## 4.6 Quantity Selector Stuck / Not Working
[TAGS: quantity, selector, stuck, zero, not working, readonly, disabled, quantity input, plus minus, increment, decrement]

### Symptom: Quantity shows 0 or can't be changed
ROOT CAUSE: Input has `readOnly`, `min`/`max` set to 0, or event listeners blocking changes.

### Fix:
```javascript
(function() {
  document.querySelectorAll('input[name="quantity"], quantity-input input, .quantity__input').forEach(input => {
    input.readOnly = false;
    input.min = '1';
    input.max = '';  // remove max limit
    input.value = input.value === '0' ? '1' : input.value;
    input.style.cssText = '';  // clear any inline style sabotage
    input.dataset.tsFixed = 'true';
    
    // Restore original value if stored
    if (input.dataset.originalValue) {
      input.value = input.dataset.originalValue;
    }
  });
  
  // Re-enable +/- buttons
  document.querySelectorAll('quantity-input button, .quantity__button').forEach(btn => {
    btn.disabled = false;
    btn.style.opacity = '1';
    btn.style.pointerEvents = 'auto';
    btn.dataset.tsFixed = 'true';
  });
})();
```


## 4.7 Widget / App Block Not Showing
[TAGS: widget, not showing, missing, app block, app embed, bundle, reviews, upsell, cross-sell, rebuy, vitals, bold, recharge, subscription, hidden widget]

### Symptom: An app's widget/block is completely gone from the page
CHECK IN ORDER:
1. **App embed not enabled** — Theme Settings → App Embeds → check toggle
   - How to detect: Search DOM for the app's container element or script
   - If script is present but container is missing → embed is disabled or section isn't rendered
2. **Container element hidden via CSS**
   - Search DOM for the widget's container: `[data-widget-id], [class*="rebuy"], [class*="bundle"], [class*="vitals"]`
   - Check computed styles: `display:none`, `visibility:hidden`, `max-height:0`, `opacity:0`
3. **Container element removed from DOM**
   - Search for the app's script tag — if present but widget container missing → JS failed to render
   - Check console for errors from the app's domain
4. **Script failed to load**
   - Check network tab for 404 or DNS failures for the app's CDN
   - Common: `net::ERR_NAME_NOT_RESOLVED` → DNS issue, external to the store
5. **Required container ID missing**
   - Many bundle apps look for `#bundle-target-product` or similar
   - If theme customizer section was modified, the container may have been removed

### Fix for hidden widget:
```css
/* Override common widget hiding patterns */
[data-widget-id],
.bundler-target-product,
.rebuy-widget,
.scd-w,
.vitals-widget,
[id*="bundle"],
[class*="bundle"],
[class*="rebuy"],
[class*="vitals"] {
  display: block !important;
  visibility: visible !important;
  opacity: 1 !important;
  max-height: none !important;
  overflow: visible !important;
  margin: initial !important;
  padding: initial !important;
  border: initial !important;
  transform: none !important;
  pointer-events: auto !important;
}
```


## 4.8 Back in Stock / Notify Me Button Missing
[TAGS: back in stock, notify me, BIS, notify button, out of stock, notification, waitlist, restock alert, bis-button, BIS_trigger, BIS_frame]

### Symptom: Out-of-stock product has no "Notify Me" button
CHECK IN ORDER:
1. **Variant is actually in stock** — Check `variant.available` and `variant.inventory_quantity`
   - BIS buttons only show for out-of-stock variants
2. **App embed not activated** — Theme Settings → App Embeds
3. **BIS script failed to load** — Check network for the app's script URL
4. **BIS script can't find the product form** — It looks for specific selectors
5. **Button is rendered but hidden via CSS**
   - Search DOM for: `.bis-button`, `.BIS_trigger`, `[class*="notify"]`, `button[name="notification-button"]`

### Fix for hidden BIS button:
```css
.bis-button,
button[name="notification-button"],
.BIS_trigger,
[class*="notify-me"],
[class*="back-in-stock"] {
  display: inline-block !important;
  visibility: visible !important;
  opacity: 1 !important;
  position: static !important;
  transform: none !important;
  pointer-events: auto !important;
  left: auto !important;
  top: auto !important;
}
```

### Common BIS app containers:
```
Klaviyo BIS:      .klaviyo-bis-trigger, [data-klaviyo-trigger]
Swym Watchlist:   .swym-button, #swym-collection-watchlist
Back in Stock:    .BIS_trigger, #BIS_frame
SC BIS:           .sc-bis-button
Notify Me:        .notify-me-button, [data-notify-me]
Amp BIS/PreOrder: [data-amp-add-to-cart], .amp-preorder-btn
```


## 4.9 Product Description Hidden / Error Message
[TAGS: description, hidden, error message, rendering error, transparent text, product description, content text]

### Symptom: Description area shows error text or is invisible
ROOT CAUSE: CSS making description text transparent + pseudo-element injecting fake error.

### Diagnostic:
```javascript
(function() {
  const descEls = document.querySelectorAll('.product__description, .product-description, [class*="product-description"]');
  descEls.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const after = getComputedStyle(el, '::after');
    console.log(`[TS-DIAG] Desc #${i} color: ${cs.color}, bg: ${cs.backgroundColor}`);
    if (after.content && after.content !== 'none') console.log(`[TS-DIAG] Desc #${i} ::after content: ${after.content}`);
  });
})();
```

### Fix:
```css
.product__description,
.product-description,
[class*="product-description"],
.product__content-text {
  color: inherit !important;
  -webkit-text-fill-color: inherit !important;
  background: transparent !important;
}
.product__description::after,
.product-description::after,
[class*="product-description"]::after {
  content: none !important;
  display: none !important;
}
```


## 4.10 Product Form Displaced / Off-screen
[TAGS: product form, displaced, off-screen, transform, translateX, invisible form, form hidden, pointer-events none, overflow hidden]

### Symptom: Product form (variant selector + add to cart) is completely gone
ROOT CAUSE: CSS `transform: translateX(200%)`, `opacity: 0.01`, `pointer-events: none`

### Diagnostic:
```javascript
(function() {
  const forms = document.querySelectorAll('product-form, .product-form, form[action*="/cart/add"]');
  forms.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const issues = [];
    if (cs.transform !== 'none') issues.push(`transform:${cs.transform}`);
    if (parseFloat(cs.opacity) < 0.5) issues.push(`opacity:${cs.opacity}`);
    if (cs.pointerEvents === 'none') issues.push('pointer-events:none');
    if (parseInt(cs.maxHeight) < 100 && parseInt(cs.maxHeight) >= 0) issues.push(`max-height:${cs.maxHeight}`);
    if (cs.overflow === 'hidden') issues.push('overflow:hidden');
    if (issues.length) console.log(`[TS-DIAG] Form #${i}: ${issues.join(', ')}`);
  });
})();
```

### Fix:
```css
product-form,
.product-form {
  transform: none !important;
  opacity: 1 !important;
  pointer-events: auto !important;
  max-height: none !important;
  overflow: visible !important;
  transition: none !important;
  visibility: visible !important;
  display: block !important;
  position: static !important;
}
```


## 4.11 Below-fold Content Missing / Blurred
[TAGS: below fold, related products, recommendations, recently viewed, complementary, blurred, hidden sections, below product]

### Symptom: Content below the main product section is missing, blurred, or tiny

### Fix:
```css
.product-recommendations,
[class*="related-product"],
[class*="recently-viewed"],
.complementary-products {
  opacity: 1 !important;
  filter: none !important;
  max-height: none !important;
  overflow: visible !important;
  pointer-events: auto !important;
  display: block !important;
  visibility: visible !important;
}
```


## 4.12 Breadcrumbs / Navigation Hidden
[TAGS: breadcrumbs, navigation, breadcrumb, collections link, hidden navigation, tiny text, invisible links]

### Symptom: Breadcrumbs or collection links are microscopic or invisible
ROOT CAUSE: `font-size: 1px`, `opacity: 0.02`, `max-height: 3px`

### Fix:
```css
.breadcrumbs, .breadcrumb,
a[href*="/collections/"] {
  font-size: inherit !important;
  line-height: inherit !important;
  opacity: 1 !important;
  max-height: none !important;
  overflow: visible !important;
}
```


## 4.13 Fetch / XHR Interceptor Detection & Fix
[TAGS: fetch, interceptor, monkey patch, XHR, XMLHttpRequest, cart blocked, 422, fake response, network intercept, cart guard, fetch hijack]

### Symptom: Cart operations fail silently or return fake errors
ROOT CAUSE: A script replaced `window.fetch` and/or `XMLHttpRequest.prototype.open` to block cart operations.

### Detection:
```javascript
(function() {
  // Check if fetch is native
  const fetchNative = window.fetch.toString().includes('native code');
  console.log('[TS-DIAG] fetch is native:', fetchNative);
  
  // Check if XHR.open is native
  const xhrNative = XMLHttpRequest.prototype.open.toString().includes('native code');
  console.log('[TS-DIAG] XHR.open is native:', xhrNative);
  
  // Try a test fetch to /cart.js to see if it's intercepted
  const testFetch = window.fetch('/cart.js');
  testFetch.then(r => {
    console.log('[TS-DIAG] /cart.js fetch status:', r.status);
    if (r.status === 422 || r.status === 403) {
      console.log('[TS-DIAG] CART FETCH IS BEING INTERCEPTED');
    }
  }).catch(e => console.log('[TS-DIAG] fetch error:', e));
})();
```

### Fix — Restore native fetch from a clean iframe:
```javascript
(function() {
  // Create a hidden iframe to get a clean window with native fetch
  const iframe = document.createElement('iframe');
  iframe.style.display = 'none';
  iframe.sandbox = 'allow-same-origin';
  document.body.appendChild(iframe);
  
  // Wait for iframe to load, then steal its native fetch
  iframe.onload = function() {
    if (iframe.contentWindow && iframe.contentWindow.fetch) {
      window.fetch = iframe.contentWindow.fetch.bind(window);
      console.log('[TS-FIX] Native fetch restored from iframe');
    }
    // Also restore XHR if needed
    if (iframe.contentWindow && iframe.contentWindow.XMLHttpRequest) {
      window.XMLHttpRequest.prototype.open = iframe.contentWindow.XMLHttpRequest.prototype.open;
      console.log('[TS-FIX] Native XHR.open restored from iframe');
    }
    // Clean up
    document.body.removeChild(iframe);
  };
  
  // Load about:blank to initialize
  iframe.src = 'about:blank';
})();
```

### Alternative fix — Check for kill switch:
Many interceptor scripts have a global flag to disable themselves:
```javascript
// Common kill switch patterns — search DOM for these:
// window.__SABOTAGE_NEUTRALIZED__ = true
// window.__CART_GUARD_DISABLED__ = true
// window.__INTERCEPT_OFF__ = true

// Search for kill switch clues:
(function() {
  // Check meta tags for hints
  document.querySelectorAll('meta').forEach(m => {
    const name = m.getAttribute('name') || '';
    const content = m.getAttribute('content') || '';
    if (name.includes('sabotage') || name.includes('guard') || name.includes('intercept') ||
        content.includes('NEUTRALIZED') || content.includes('DISABLED') || content.includes('kill')) {
      console.log(`[TS-DIAG] KILL SWITCH CLUE: meta[name="${name}"] content="${content}"`);
    }
  });
  
  // Check for known global flags
  const flags = ['__SABOTAGE_NEUTRALIZED__', '__CART_GUARD_DISABLED__', '__INTERCEPT_OFF__', 
                 '__BLOCK_DISABLED__', '__BYPASS__'];
  flags.forEach(f => {
    if (f in window) console.log(`[TS-DIAG] Flag found: window.${f} = ${window[f]}`);
  });
})();
```


## 4.14 Form Submit Event Interceptor
[TAGS: form submit, interceptor, event listener, capture phase, preventDefault, stopImmediatePropagation, form blocked, submit blocked]

### Symptom: Form submission is silently blocked (form exists, variant exists, but submit does nothing)
ROOT CAUSE: A capture-phase event listener on `document` or the form is calling `preventDefault()`.

### Detection:
```javascript
// This won't show listeners directly, but we can test:
(function() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) { console.log('[TS-DIAG] No cart form found'); return; }
  
  // Try submitting programmatically and see if it's blocked
  const testEvent = new Event('submit', { bubbles: true, cancelable: true });
  const wasBlocked = !form.dispatchEvent(testEvent);
  console.log('[TS-DIAG] Form submit was blocked:', wasBlocked);
  
  // Check if the form has the right action
  console.log('[TS-DIAG] Form action:', form.action);
  console.log('[TS-DIAG] Form method:', form.method);
})();
```

### Fix — Clone form to strip all event listeners:
```javascript
(function() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;
  
  const newForm = form.cloneNode(true);
  form.parentNode.replaceChild(newForm, form);
  
  // Re-attach the product-form custom element behavior if needed
  const productForm = newForm.closest('product-form');
  if (productForm) {
    // Trigger reconnection
    const parent = productForm.parentNode;
    const next = productForm.nextSibling;
    parent.removeChild(productForm);
    parent.insertBefore(productForm, next);
  }
  
  console.log('[TS-FIX] Form cloned to strip event interceptors');
})();
```


## 4.15 MutationObserver Re-sabotage Detection
[TAGS: MutationObserver, re-sabotage, auto-revert, changes reverted, persistent sabotage, infinite loop, observer, disconnect, mutation]

### Symptom: Your fixes keep getting reverted (element re-disables, styles re-applied)
ROOT CAUSE: A MutationObserver is watching for changes and re-applying sabotage.

### Detection:
```javascript
// Mark an element, change it, and see if it reverts:
(function() {
  const btn = document.querySelector('button[name="add"], .product-form__submit');
  if (!btn) return;
  
  btn.dataset.tsTestMark = Date.now().toString();
  const origDisabled = btn.disabled;
  btn.disabled = false;
  
  setTimeout(() => {
    if (btn.disabled === true && origDisabled === true) {
      console.log('[TS-DIAG] MUTATION OBSERVER DETECTED — button was re-disabled within 2 seconds');
    } else {
      console.log('[TS-DIAG] No MutationObserver re-sabotage detected');
    }
  }, 2000);
})();
```

### Fix strategy (in priority order):
1. **Find the kill switch** — Search DOM for meta tags, global flags, or comments with "neutralize", "disable", "kill", "sabotage"
2. **Set the kill switch** — e.g., `window.__SABOTAGE_NEUTRALIZED__ = true;`
3. **If no kill switch exists** — Use your own MutationObserver to counter-fix:
```javascript
(function() {
  const btn = document.querySelector('button[name="add"], .product-form__submit');
  if (!btn) return;
  
  const protector = new MutationObserver(() => {
    btn.disabled = false;
    btn.removeAttribute('aria-disabled');
    btn.style.opacity = '1';
    btn.style.pointerEvents = 'auto';
    btn.style.cursor = 'pointer';
    btn.style.zIndex = 'auto';
  });
  
  protector.observe(btn, {
    attributes: true,
    attributeFilter: ['disabled', 'aria-disabled', 'style', 'class']
  });
  
  // Also protect with CSS
  const style = document.createElement('style');
  const btnId = btn.id;
  if (btnId) {
    style.textContent = `#${btnId} { opacity: 1 !important; pointer-events: auto !important; z-index: auto !important; cursor: pointer !important; }`;
    document.head.appendChild(style);
  }
  
  // Initial fix
  btn.disabled = false;
  btn.removeAttribute('aria-disabled');
  btn.dataset.tsFixed = 'true';
  
  console.log('[TS-FIX] MutationObserver protector installed');
})();
```

4. **Mark fixed elements** — Always set `btn.dataset.tsFixed = 'true'` on elements you fix. Well-written sabotage scripts check for this and skip already-fixed elements.


## 4.16 Console Error Spam (Fake Errors)
[TAGS: console error, fake error, spam, BundleEngine, CartGuard, NotifyMe, RechargeSubscriptions, ThemeEngine, fake console, spoofed error]

### Symptom: Console filled with dramatic-looking errors that don't match reality
RED FLAGS that errors are FAKE:
- Error references a CDN/domain that doesn't exist (check DNS)
- Error says "v3.2.1" or specific version but the app isn't installed
- Error stack trace points to minified URLs that 404 when you visit them
- Multiple errors from different "apps" all appearing at the same time
- Errors contain overly specific diagnostic messages ("Retry #3 failed", "Code: CG-403-VARIANT")

### Verification:
```javascript
// Check if error source scripts actually exist:
(function() {
  const suspectUrls = [
    'https://cdn.bundle-app.io/v3/engine.min.js',
    'https://cdn.notify-bis.io/v4/widget.js',
    // Add more from the console errors you see
  ];
  
  suspectUrls.forEach(url => {
    fetch(url, { method: 'HEAD', mode: 'no-cors' })
      .then(r => console.log(`[TS-DIAG] ${url} — reachable`))
      .catch(e => console.log(`[TS-DIAG] ${url} — DOES NOT EXIST (fake error source)`));
  });
})();
```

If errors are fake → they're generated by a sabotage script. Find and neutralize it (see Section 4.20).


## 4.17 Selling Plan / Subscription Widget Broken
[TAGS: selling plan, subscription, recharge, bold, appstle, loop, seal, subscription widget, recurring, subscribe and save]

### Symptom: "Subscribe and Save" option missing or broken on product page
CHECK IN ORDER:
1. **Product has selling plans?** — Check product JSON `selling_plan_groups` array
2. **App embed enabled?** — Theme Settings → App Embeds
3. **Widget container present?** — Search DOM for app-specific selectors
4. **Form has selling_plan input?** — Look for `input[name="selling_plan"]`

### Key selectors by app:
```
Recharge:    .rc-widget, .rc-container, [data-recharge], #recurring-options
Bold:        .bold-ro, #bold_subscriptions_widget, [data-bold-widget]
Seal:        .sls-widget, [data-seal-subscription]
Appstle:     .appstle_sub_widget, #appstle_subscription_widget
Loop:        .loop-subscription-widget, [data-loop-subscription]
Native:      selling-plan-selector, .selling-plan-group
```

### Minimal selling plan form fix:
```javascript
// If widget is broken but product has selling plans, inject a basic selector:
(function() {
  const handle = window.location.pathname.split('/products/')[1]?.split('?')[0];
  if (!handle) return;
  
  fetch('/products/' + handle + '.js')
    .then(r => r.json())
    .then(product => {
      if (!product.selling_plan_groups || product.selling_plan_groups.length === 0) {
        console.log('[TS-DIAG] Product has no selling plans');
        return;
      }
      
      const form = document.querySelector('form[action*="/cart/add"]');
      if (!form || form.querySelector('input[name="selling_plan"]')) return;
      
      // Create a hidden selling plan input
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'selling_plan';
      input.value = ''; // Empty means one-time purchase
      form.appendChild(input);
      
      console.log('[TS-FIX] Added selling_plan input to form. Groups:', product.selling_plan_groups.length);
    });
})();
```


## 4.18 Dynamic Checkout Buttons Not Showing
[TAGS: dynamic checkout, buy now, shop pay, apple pay, google pay, express checkout, payment button, shopify payment button]

### Symptom: "Buy it now" / Shop Pay / Apple Pay buttons missing

CHECK:
1. **Test mode?** — Dynamic checkout buttons don't show in development/test mode
2. **Payment methods configured?** — Must have accelerated checkout methods enabled in Settings → Payments
3. **Product type** — Gift cards, subscription-only products may not support dynamic checkout
4. **Container hidden?** — Search for `.shopify-payment-button`
5. **Script blocked?** — Check network for `shopify_payment_button` script loading

```javascript
(function() {
  const container = document.querySelector('.shopify-payment-button');
  if (!container) {
    console.log('[TS-DIAG] No .shopify-payment-button container found');
    return;
  }
  const cs = getComputedStyle(container);
  console.log('[TS-DIAG] Payment button display:', cs.display);
  console.log('[TS-DIAG] Payment button visibility:', cs.visibility);
  console.log('[TS-DIAG] Payment button children:', container.children.length);
  console.log('[TS-DIAG] data-has-selling-plan:', container.getAttribute('data-has-selling-plan'));
})();
```


## 4.19 Cart Drawer / Cart Notification Not Updating
[TAGS: cart drawer, cart notification, not updating, stale cart, cart count, cart badge, cart icon, ajax cart, cart refresh]

### Symptom: Item adds to cart but drawer/badge doesn't update

ROOT CAUSE: After adding to cart, the theme expects specific events or Section Rendering API calls to update the UI.

### How Dawn handles it:
```javascript
// After successful /cart/add.js, Dawn does:
// 1. Fetches fresh cart drawer section HTML
fetch(window.Shopify.routes.root + `?sections=cart-drawer,cart-icon-bubble`)
  .then(r => r.json())
  .then(sections => {
    // 2. Replaces the cart drawer HTML
    document.getElementById('cart-drawer').innerHTML = sections['cart-drawer'];
    // 3. Dispatches a custom event
    document.dispatchEvent(new CustomEvent('cart:refresh'));
  });
```

### Fix — Force cart UI refresh:
```javascript
(function() {
  // Method 1: Dispatch cart refresh events
  document.dispatchEvent(new CustomEvent('cart:refresh'));
  document.dispatchEvent(new CustomEvent('cart-update'));
  
  // Method 2: Trigger Section Rendering API refresh
  fetch(window.Shopify.routes.root + '?sections=cart-drawer,cart-icon-bubble,cart-live-region-text')
    .then(r => r.json())
    .then(sections => {
      Object.entries(sections).forEach(([id, html]) => {
        const el = document.getElementById('shopify-section-' + id);
        if (el) el.outerHTML = html;
      });
    });
  
  // Method 3: Update cart count badge directly
  fetch(window.Shopify.routes.root + 'cart.js')
    .then(r => r.json())
    .then(cart => {
      document.querySelectorAll('.cart-count-bubble span, [data-cart-count]').forEach(el => {
        el.textContent = cart.item_count;
      });
    });
})();
```


## 4.20 Rogue App / Sabotage Detection (Master Checklist)
[TAGS: sabotage, rogue app, detection, kill switch, neutralize, guard, intercept, malicious, anti-tamper, sabotage detection, comprehensive fix, master fix]

When multiple things are broken simultaneously, suspect a rogue script. Follow this master checklist:

### Step 1: Search for kill switch
```
search_dom("sabotage|neutralize|kill|guard|intercept|block|disable")
search_console("guard|blocked|intercepted|suspended|enforcement")
```
If found: Set the flag (e.g., `window.__SABOTAGE_NEUTRALIZED__ = true;`)

### Step 2: Check for fetch/XHR interceptors
```javascript
console.log('fetch native:', window.fetch.toString().includes('native code'));
console.log('XHR native:', XMLHttpRequest.prototype.open.toString().includes('native code'));
```
If patched: Restore from iframe (see Section 4.13)

### Step 3: Check for form submit interceptors
```javascript
const form = document.querySelector('form[action*="/cart/add"]');
const testEvt = new Event('submit', { bubbles: true, cancelable: true });
console.log('submit blocked:', !form.dispatchEvent(testEvt));
```
If blocked: Clone form (see Section 4.14)

### Step 4: Check for MutationObserver re-sabotage
Change a disabled button, wait 2 seconds, check if reverted.
If reverted: Counter-observer or kill switch (see Section 4.15)

### Step 5: Remove injected sabotage elements
```javascript
// Remove fake error banners
document.querySelectorAll('[id*="sabotage"], [class*="sabotage"]').forEach(el => el.remove());

// Remove sabotage style tags
document.querySelectorAll('style').forEach(s => {
  if (s.textContent.includes('sabotage') || s.textContent.includes('z-index: -999') || 
      s.textContent.includes('clip-path: inset')) {
    s.remove();
  }
});
```

### Step 6: Apply comprehensive CSS counter-fix
Inject CSS that overrides all common hiding/breaking patterns (combine fixes from Sections 4.1-4.12).

### Step 7: Mark all fixed elements
```javascript
document.querySelectorAll('[data-ts-fixed]').forEach(el => { /* already fixed */ });
// Set data-ts-fixed="true" on every element you repair
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 5: CSS OVERRIDE TECHNIQUES & SPECIFICITY
# ═══════════════════════════════════════════════════════════════════

## 5.1 CSS Specificity Rules
[TAGS: CSS, specificity, important, override, inline style, specificity war, selector weight, cascade]

Specificity hierarchy (highest to lowest):
1. `!important` declarations (highest priority within same origin)
2. Inline styles (`style="..."` attribute)
3. ID selectors (`#myId`)
4. Class selectors (`.myClass`), attribute selectors (`[name="id"]`), pseudo-classes (`:hover`)
5. Element selectors (`div`, `button`), pseudo-elements (`::after`)

WHEN `!important` FIGHTS `!important`:
- More specific selector wins
- If same specificity → last one in source order wins
- Inline `style="opacity: 0 !important"` vs stylesheet `#myId { opacity: 1 !important; }` → **ID selector wins** because ID specificity is higher than inline for `!important` declarations

PRACTICAL RULES FOR FIXING:
```css
/* If the sabotage uses class selectors with !important: */
.product-form__submit { opacity: 0 !important; }

/* Beat it with an ID selector + !important: */
#ProductSubmitButton-template--12345__main { opacity: 1 !important; }

/* If you don't know the ID, use a double-class or attribute selector: */
button.product-form__submit[name="add"] { opacity: 1 !important; }

/* Nuclear option — inject style tag AFTER sabotage style: */
/* (later !important declarations win at same specificity) */
```

## 5.2 Injecting Counter-CSS Effectively
[TAGS: inject CSS, counter CSS, override CSS, style injection, style tag, CSS fix]

### Method 1: inject_css action (via TS Sidekick)
```json
{
  "action": "inject_css",
  "payload": {
    "css": "#ProductSubmitButton-template--12345__main { opacity: 1 !important; }"
  }
}
```
This appends a `<style>` tag to `<head>`. Being later in DOM order, it wins ties.

### Method 2: Inject via JS for dynamic selectors
```javascript
(function() {
  const style = document.createElement('style');
  style.id = 'ts-sidekick-fix';
  
  // Build selectors dynamically using actual element IDs
  const btn = document.querySelector('button[name="add"], .product-form__submit');
  const btnSelector = btn?.id ? `#${btn.id}` : 'button[name="add"]';
  
  style.textContent = `
    ${btnSelector} {
      opacity: 1 !important;
      z-index: auto !important;
      pointer-events: auto !important;
      cursor: pointer !important;
      display: flex !important;
      clip-path: none !important;
      position: relative !important;
    }
  `;
  
  document.head.appendChild(style);
})();
```

### Method 3: Remove offending stylesheets
```javascript
// Find and remove sabotage style tags:
document.querySelectorAll('style').forEach(s => {
  if (s.textContent.includes('z-index: -999') || 
      s.textContent.includes('clip-path: inset') ||
      s.textContent.includes('-webkit-text-fill-color: transparent')) {
    console.log('[TS-FIX] Removing sabotage style tag:', s.textContent.substring(0, 100));
    s.remove();
  }
});

// Find and disable sabotage link tags (external CSS):
document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
  // Only disable if you're sure it's the sabotage CSS
  // Check the href for suspicious domains
  if (link.href.includes('suspicious-app-domain.com')) {
    link.disabled = true;
  }
});
```


## 5.3 Common CSS Hiding Patterns Reference
[TAGS: CSS hiding, hidden element, detection, invisible, display none, visibility hidden, opacity zero, clip path, transform, z-index negative, font size zero, pointer events none]

Quick reference of all CSS techniques used to hide elements:

| Technique | CSS | Detection | Override |
|-----------|-----|-----------|----------|
| Display none | `display: none` | `cs.display === 'none'` | `display: block !important` |
| Visibility hidden | `visibility: hidden` | `cs.visibility === 'hidden'` | `visibility: visible !important` |
| Zero opacity | `opacity: 0` | `cs.opacity === '0'` | `opacity: 1 !important` |
| Transparent color | `color: transparent` | `cs.color` has alpha 0 | `color: inherit !important` |
| Text fill color | `-webkit-text-fill-color: transparent` | check computed | `-webkit-text-fill-color: inherit !important` |
| Zero font size | `font-size: 0px` | `parseFloat(cs.fontSize) === 0` | `font-size: inherit !important` |
| Negative z-index | `z-index: -999` | `parseInt(cs.zIndex) < 0` | `z-index: auto !important` |
| Clip path | `clip-path: inset(50%)` | `cs.clipPath !== 'none'` | `clip-path: none !important` |
| Off-screen position | `position: fixed; left: -9999px` | `parseInt(cs.left) < -1000` | `position: static !important` |
| Transform off-screen | `transform: translateX(-9999px)` | `cs.transform !== 'none'` | `transform: none !important` |
| Zero size | `width: 0; height: 0; overflow: hidden` | `el.offsetWidth === 0` | `width: auto !important; height: auto !important` |
| Scale to zero | `transform: scale(0.01)` | check transform | `transform: none !important` |
| Pointer events none | `pointer-events: none` | `cs.pointerEvents === 'none'` | `pointer-events: auto !important` |
| Max-height clamp | `max-height: 0; overflow: hidden` | `parseInt(cs.maxHeight) === 0` | `max-height: none !important; overflow: visible !important` |
| Negative letter spacing | `letter-spacing: -9999px` | large negative value | `letter-spacing: normal !important` |
| Text shadow removal | `text-shadow: none` | only relevant if text was styled with shadow | `text-shadow: inherit !important` |


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 6: JAVASCRIPT DEFENSE PATTERNS
# ═══════════════════════════════════════════════════════════════════

## 6.1 Detecting Monkey-Patched Native Functions
[TAGS: monkey patch, native function, detection, toString, native code, patched, overridden, hijacked, tampered]

```javascript
// Check any function for native-ness:
function isNative(fn) {
  return typeof fn === 'function' && fn.toString().includes('[native code]');
}

// Critical functions to check:
console.log('fetch:', isNative(window.fetch));
console.log('XHR.open:', isNative(XMLHttpRequest.prototype.open));
console.log('XHR.send:', isNative(XMLHttpRequest.prototype.send));
console.log('addEventListener:', isNative(EventTarget.prototype.addEventListener));
console.log('querySelector:', isNative(Document.prototype.querySelector));
console.log('createElement:', isNative(Document.prototype.createElement));
console.log('setTimeout:', isNative(window.setTimeout));
console.log('setInterval:', isNative(window.setInterval));
console.log('JSON.parse:', isNative(JSON.parse));
console.log('JSON.stringify:', isNative(JSON.stringify));
```


## 6.2 Restoring Native Functions
[TAGS: restore, native function, fetch, XHR, iframe, clean context, reset, unhijack]

```javascript
// Method 1: From a clean iframe
(function() {
  const iframe = document.createElement('iframe');
  iframe.style.display = 'none';
  document.body.appendChild(iframe);
  
  // Restore specific functions:
  window.fetch = iframe.contentWindow.fetch.bind(window);
  XMLHttpRequest.prototype.open = iframe.contentWindow.XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.send = iframe.contentWindow.XMLHttpRequest.prototype.send;
  
  document.body.removeChild(iframe);
})();

// Method 2: From a stored reference (if available)
// Some scripts store the original before patching:
// window.__originalFetch, window._origFetch, etc.
// Check for these before creating an iframe.
```


## 6.3 Finding and Removing Event Listeners
[TAGS: event listener, remove, find, getEventListeners, clone element, capture phase, submit handler, click handler]

```javascript
// Method 1: Clone the element (removes ALL listeners)
function stripListeners(el) {
  const clone = el.cloneNode(true);
  el.parentNode.replaceChild(clone, el);
  return clone;
}

// Method 2: Use Chrome DevTools protocol (if available via extension debugger)
// getEventListeners(element) — only works in DevTools console, not in page scripts

// Method 3: Override addEventListener to track listeners
// (Must be done BEFORE sabotage scripts run — usually too late)

// Method 4: For document-level capture listeners (form submit blocking):
// Clone the form — capture listeners on document still fire, but...
// Better: Find the specific listener function and remove it
// If the sabotage uses named functions, you can find them:
document.removeEventListener('submit', window.sabotageSubmitHandler, true);
```


## 6.4 data-ts-fixed Pattern
[TAGS: ts-fixed, data attribute, mark fixed, prevent re-sabotage, fixed marker, already fixed]

Always mark elements you fix with `data-ts-fixed="true"`. This serves two purposes:
1. Well-written sabotage scripts check for this and skip the element
2. You can avoid double-fixing in subsequent turns

```javascript
// Before fixing an element:
if (element.dataset.tsFixed) return; // Already fixed, skip

// After fixing:
element.dataset.tsFixed = 'true';

// In CSS fixes, add:
[data-ts-fixed] {
  /* These elements have been fixed by TS Sidekick */
}
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 7: SHOPIFY APP-SPECIFIC PATTERNS
# ═══════════════════════════════════════════════════════════════════

## 7.1 Common App Selectors Reference
[TAGS: app selectors, app containers, app elements, rebuy, vitals, bold, recharge, klaviyo, yotpo, loox, judge.me, stamped, okendo, omnisend, privy, justuno, smile, loyalty lion, aftership]

### Product Reviews Apps:
```
Judge.me:        .jdgm-widget, .jdgm-rev-widg, .jdgm-badge
Yotpo:           .yotpo-widget-instance, .yotpo-bottomline, .yotpo-reviews
Loox:            .loox-widget, .loox-reviews, [data-loox-id]
Stamped:         .stamped-widget, .stamped-reviews, [data-stamped-widget]
Okendo:          .okeReviews, [data-oke-widget], .oke-widget
Shopify Reviews: .spr-widget, .spr-reviews, .spr-badge
```

### Upsell / Cross-sell Apps:
```
Rebuy:           .rebuy-widget, [data-rebuy-id], .rebuy-smart-cart
Vitals:          .vitals-widget, [class*="vitals"], [data-vitals]
Bold Upsell:     .bold-upsell, [data-bold-widget]
Frequently Bought Together: .fbt-widget, [data-fbt]
Honeycomb:       .upsell-widget, [data-honeycomb]
In Cart Upsell:  .icu-widget, [data-icu-widget]
```

### Bundle Apps:
```
Bundler:         .bundler-target-product, [data-bundler]
Wide Bundles:    .wbundles-container, [data-wide-bundles]
PickyStory:      .picky-story-widget, [data-pickystory]
Bundle Builder:  [data-bundle-builder]
```

### Subscription Apps:
```
Recharge:        .rc-widget, .rc-container, [data-recharge]
Bold Subscriptions: .bold-ro, #bold_subscriptions_widget
Seal:            .sls-widget, [data-seal-subscription]
Appstle:         .appstle_sub_widget
Loop:            .loop-subscription-widget
PayWhirl:        .pw-widget, [data-paywhirl]
```

### Email / Marketing Apps:
```
Klaviyo:         .klaviyo-form, [data-klaviyo], .klaviyo-bis-trigger
Omnisend:        .omnisend-form, [data-omnisend]
Privy:           #privy-popup, .privy-popup
Justuno:         #ju_iframe, .ju-popup
Mailchimp:       .mailchimp-form, [data-mailchimp]
```

### Loyalty Apps:
```
Smile.io:        #smile-ui-container, .smile-widget
LoyaltyLion:     .loyaltylion-widget, [data-loyaltylion]
Yotpo Loyalty:   .yotpo-loyalty-widget
```

### Shipping / Tracking:
```
AfterShip:       .aftership-widget, [data-aftership]
Route:           .route-widget, #route-widget
```


## 7.2 App Uninstall Residue
[TAGS: uninstall, residue, leftover code, removed app, ghost code, orphaned script, cleanup]

When apps are uninstalled, they often leave behind:
1. **ScriptTag entries** — check `content_for_header` output for dead script URLs
2. **Theme file modifications** — code added to theme.liquid, product templates, snippets
3. **App block placeholders** — empty `<div class="shopify-block">` elements
4. **CSS/JS files in assets/** — some apps copy files to the theme
5. **Liquid snippets** — `snippets/app-name-*.liquid` files
6. **Metafield data** — product/shop metafields from the app

### Detecting orphaned scripts:
```javascript
(function() {
  // Find scripts that 404 or fail to load
  document.querySelectorAll('script[src]').forEach(s => {
    fetch(s.src, { method: 'HEAD', mode: 'no-cors' })
      .then(r => {
        if (!r.ok) console.log('[TS-DIAG] Dead script:', s.src);
      })
      .catch(() => console.log('[TS-DIAG] Unreachable script:', s.src));
  });
})();
```


## 7.3 Preorder App Patterns
[TAGS: preorder, pre-order, preorder button, preorder app, back in stock preorder, amp preorder, preorder now, coming soon]

Preorder apps typically work by:
1. Checking if product has a specific tag (e.g., "preorder-enabled", "pre-order")
2. Checking if variant has `inventory_policy: "continue"` and `inventory_quantity <= 0`
3. Finding the Add to Cart button via selectors
4. Changing button text to "Pre-order Now" or "Pre-order"
5. Optionally adding messaging below the button

### Common preorder selectors:
```
Amp PreOrder:    [data-amp-add-to-cart], .amp-preorder-btn
PreOrder Now:    .preorder-button, [data-preorder]
Preorder Manager: .pm-preorder-btn
Globo PreOrder:  .globo-preorder-btn
```

### Why preorder buttons fail to show:
1. **Button selector mismatch** — App looks for `button[name="add"]` but theme uses different structure
2. **Tag missing** — Product doesn't have the required tag
3. **Variant selector missing** — App can't determine current variant
4. **Inventory policy wrong** — Set to "deny" instead of "continue"
5. **App script runs before DOM ready** — Button element doesn't exist yet when script runs

### Manual preorder button fix:
```javascript
(function() {
  const handle = window.location.pathname.split('/products/')[1]?.split('?')[0];
  if (!handle) return;
  
  fetch('/products/' + handle + '.js')
    .then(r => r.json())
    .then(product => {
      const isPreorder = product.tags.some(t => 
        t.toLowerCase().includes('preorder') || t.toLowerCase().includes('pre-order')
      );
      if (!isPreorder) return;
      
      const variantId = new URLSearchParams(window.location.search).get('variant') || product.variants[0].id;
      const variant = product.variants.find(v => v.id == variantId);
      
      if (variant && variant.inventory_policy === 'continue' && variant.inventory_quantity <= 0) {
        const btn = document.querySelector('button[name="add"], .product-form__submit, button[type="submit"]');
        if (btn) {
          btn.textContent = 'Pre-order Now';
          btn.classList.add('preorder-active');
          btn.disabled = false;
        }
      }
    });
})();
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 8: DIAGNOSTIC SEARCH SHORTCUTS
# ═══════════════════════════════════════════════════════════════════

## 8.1 First-Turn Search Queries
[TAGS: first turn, initial search, quick scan, diagnostic queries, first observation, starting point]

After your first observation, run these searches to quickly surface issues:

```
search_dom("disabled|aria-disabled")        → Find disabled interactive elements
search_dom("[HIDDEN:")                       → Find elements flagged as hidden
search_dom("sabotage|guard|neutralize")      → Find sabotage markers
search_console("error|blocked|failed")       → Find real errors
search_console("guard|intercept|suspended")  → Find fake/sabotage errors
search_dom("product-form|cart/add")          → Find the product form
search_dom("name=\"id\"")                    → Find variant selector
```


## 8.2 Issue-Specific Search Queries
[TAGS: search queries, specific searches, targeted search, query reference]

**Cart/form issues:**
```
search_dom("form|action|cart/add")
search_dom("name=\"id\"|name=\"quantity\"")
search_dom("submit|add-to-cart|product-form__submit")
search_network("cart/add|cart/update")
search_console("variant|cart|422|403")
```

**Price issues:**
```
search_dom("price-item|money|price__")
search_dom("compare_at|sale|regular")
```

**App/widget issues:**
```
search_dom("widget|bundle|rebuy|vitals|bis|notify|recharge|subscription")
search_dom("app-block|shopify-block|data-block-type")
search_console("widget|bundle|subscription|recharge|bold")
search_network("extensions|apps")
```

**Script issues:**
```
search_dom("script|src=")
search_console("TypeError|ReferenceError|SyntaxError")
search_console("404|net::ERR")
search_network("FAILED|404|500")
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 9: SHOPIFY THEME VARIANTS & DIFFERENCES
# ═══════════════════════════════════════════════════════════════════

## 9.1 Dawn (Default Reference Theme)
[TAGS: dawn, theme, default theme, reference theme, shopify dawn, OS 2.0]

- Uses Web Components (custom elements) extensively
- No jQuery dependency
- JSON templates
- CSS custom properties for theming
- All JS is vanilla ES6
- Product form: `<product-form>` custom element
- Variant picker: `<variant-selects>` or `<variant-radios>`
- Cart: AJAX-based with `<cart-drawer>` or `<cart-notification>`
- Deferred loading for videos/3D: `<deferred-media>`
- Image slider: `<slider-component>`

## 9.2 Non-Dawn / Custom Themes
[TAGS: custom theme, non-dawn, vintage theme, jQuery, non-standard, custom architecture, Preact, React, Vue]

Some themes use completely different architectures:
- **jQuery-based** — older themes, use `$('.product-form').on('submit', ...)`
- **Preact/React** — some modern themes render product forms via JS frameworks
  - No static DOM elements for form, variant, or button
  - Everything renders client-side from a JSON state object
  - Standard selectors like `form[action*="/cart/add"]` won't find anything
  - Look for: `productState`, `window.__PREACT__`, `window.__NEXT_DATA__`
- **Vue-based** — similar issues to React
- **Custom cart implementations** — may not use /cart/add.js at all
  - Could use Storefront API, Buy SDK, or custom endpoints
- **Page builder themes** — Shogun, GemPages, PageFly, Zipify
  - Add extra wrapper elements
  - May have their own product form components
  - Selectors may be different from standard themes

### How to detect theme type:
```javascript
(function() {
  // Check for framework indicators
  if (document.querySelector('[data-preact], [data-react-root], #__next')) 
    console.log('[TS-DIAG] React/Preact/Next.js detected');
  if (document.querySelector('[data-v-], [v-cloak]')) 
    console.log('[TS-DIAG] Vue.js detected');
  if (window.jQuery || window.$) 
    console.log('[TS-DIAG] jQuery detected, version:', (window.jQuery || window.$).fn?.jquery);
  if (window.Shopify?.theme) 
    console.log('[TS-DIAG] Theme:', JSON.stringify(window.Shopify.theme));
  
  // Check for page builders
  if (document.querySelector('[data-shogun], .shg-row')) console.log('[TS-DIAG] Shogun page builder');
  if (document.querySelector('[data-pf-type], .pf-']) console.log('[TS-DIAG] PageFly page builder');
  if (document.querySelector('.gempages, [data-gp]')) console.log('[TS-DIAG] GemPages page builder');
  
  // Check product form approach
  const standardForm = document.querySelector('form[action*="/cart/add"]');
  const customElement = document.querySelector('product-form');
  const hiddenInput = document.querySelector('input[name="id"]');
  console.log('[TS-DIAG] Standard form:', !!standardForm);
  console.log('[TS-DIAG] product-form element:', !!customElement);
  console.log('[TS-DIAG] Variant input:', !!hiddenInput, hiddenInput?.value);
})();
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 10: COMPREHENSIVE DIAGNOSTIC INJECTION
# ═══════════════════════════════════════════════════════════════════

## 10.1 Master Diagnostic Script
[TAGS: master diagnostic, comprehensive diagnostic, full check, page health, diagnostic injection, health check, full scan]

Inject this on any product page to get a complete health report:

```javascript
(function() {
  const results = { issues: [], info: [] };
  
  // 1. Theme & environment
  results.info.push('Theme: ' + JSON.stringify(window.Shopify?.theme));
  results.info.push('Page type: ' + window.ShopifyAnalytics?.meta?.page?.pageType);
  results.info.push('URL: ' + window.location.href);
  
  // 2. Product form check
  const form = document.querySelector('form[action*="/cart/add"]');
  const productForm = document.querySelector('product-form');
  if (!form && !productForm) results.issues.push('CRITICAL: No product form found');
  if (form && !form.querySelector('input[name="id"], select[name="id"]')) 
    results.issues.push('CRITICAL: No variant input (name="id") in form');
  
  // 3. Variant input
  const variantInput = document.querySelector('input[name="id"], select[name="id"]');
  if (variantInput) {
    if (!variantInput.value) results.issues.push('CRITICAL: Variant input exists but value is EMPTY');
    if (variantInput.disabled) results.issues.push('WARNING: Variant input is disabled');
    results.info.push('Variant ID: ' + variantInput.value);
  }
  
  // 4. Submit button
  const btn = document.querySelector('button[name="add"], .product-form__submit, button[type="submit"]');
  if (btn) {
    if (btn.disabled) results.issues.push('CRITICAL: Submit button is disabled');
    const cs = getComputedStyle(btn);
    if (parseFloat(cs.opacity) < 0.5) results.issues.push('WARNING: Button opacity: ' + cs.opacity);
    if (parseInt(cs.zIndex) < 0) results.issues.push('WARNING: Button z-index: ' + cs.zIndex);
    if (cs.pointerEvents === 'none') results.issues.push('WARNING: Button pointer-events: none');
    if (btn.dataset.sabotageTooltip) results.issues.push('CRITICAL: Button has sabotage tooltip');
    results.info.push('Button text: ' + btn.textContent.trim());
  } else {
    results.issues.push('CRITICAL: No submit button found');
  }
  
  // 5. Price check
  const priceEls = document.querySelectorAll('.price-item');
  priceEls.forEach((el, i) => {
    const cs = getComputedStyle(el);
    if (cs.color === 'rgba(0, 0, 0, 0)' || cs.color === 'transparent')
      results.issues.push('WARNING: Price #' + i + ' has transparent color');
    if (parseFloat(cs.fontSize) === 0)
      results.issues.push('WARNING: Price #' + i + ' has font-size: 0');
  });
  
  // 6. fetch/XHR integrity
  if (!window.fetch.toString().includes('native code'))
    results.issues.push('CRITICAL: window.fetch has been monkey-patched');
  if (!XMLHttpRequest.prototype.open.toString().includes('native code'))
    results.issues.push('CRITICAL: XMLHttpRequest.open has been monkey-patched');
  
  // 7. Sabotage markers
  document.querySelectorAll('meta').forEach(m => {
    const name = m.getAttribute('name') || '';
    const content = m.getAttribute('content') || '';
    if (/(sabotage|guard|intercept|neutralize|kill)/i.test(name + content))
      results.issues.push('SABOTAGE CLUE: meta[name="' + name + '"] content="' + content + '"');
  });
  
  // 8. Hidden elements count
  let hiddenCount = 0;
  document.querySelectorAll('.product *').forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') hiddenCount++;
  });
  results.info.push('Hidden elements in .product: ' + hiddenCount);
  
  // 9. Product data availability
  const handle = window.location.pathname.split('/products/')[1]?.split('?')[0];
  if (handle) {
    results.info.push('Product handle: ' + handle);
  }
  
  // Output
  console.log('[TS-HEALTH] === PAGE HEALTH REPORT ===');
  console.log('[TS-HEALTH] Issues found: ' + results.issues.length);
  results.issues.forEach(i => console.log('[TS-HEALTH] ' + i));
  console.log('[TS-HEALTH] --- Info ---');
  results.info.forEach(i => console.log('[TS-HEALTH] ' + i));
  console.log('[TS-HEALTH] === END REPORT ===');
})();
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 11: PREORDER & INVENTORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

## 11.1 Inventory Policy & Preorder Logic
[TAGS: inventory, preorder, inventory policy, continue selling, deny, out of stock, oversell, backorder, available, stock]

Shopify has two inventory policies per variant:

**"deny"** (default): Cannot be purchased when `inventory_quantity <= 0`
- Variant `available` becomes `false`
- Add to Cart button should show "Sold out"

**"continue"**: CAN be purchased even at `inventory_quantity <= 0`
- Variant `available` stays `true`
- This is how preorder works — customer can buy even when stock is 0
- Button should say "Pre-order" instead of "Add to cart"

### How preorder apps detect preorder state:
```javascript
// Typical preorder check:
const isPreorder = (
  variant.inventory_policy === 'continue' &&
  variant.inventory_quantity <= 0 &&
  product.tags.includes('preorder-enabled')  // app-specific tag
);
```

### Checking inventory from the frontend:
```javascript
// Method 1: From product JSON
fetch('/products/handle.js')
  .then(r => r.json())
  .then(product => {
    product.variants.forEach(v => {
      console.log(`${v.title}: qty=${v.inventory_quantity}, policy=${v.inventory_policy}, available=${v.available}`);
    });
  });

// Method 2: From Liquid (server-rendered, in DOM)
// Look for: data-inventory-quantity, data-available, data-inventory-policy attributes
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 12: CHECKOUT & PAYMENT ISSUES
# ═══════════════════════════════════════════════════════════════════

## 12.1 Checkout Redirect Issues
[TAGS: checkout, redirect, checkout button, proceed to checkout, checkout URL, cart redirect]

### Standard checkout flow:
1. Form submits to `/cart/add` (traditional) or AJAX to `/cart/add.js`
2. If traditional: Shopify redirects to `/cart` or `/checkout` based on settings
3. If AJAX: Theme JS decides where to go (cart drawer, cart page, or checkout)
4. Checkout URL: `/checkout` (or custom domain if configured)

### If checkout button does nothing:
```javascript
// Check the checkout form
const checkoutForm = document.querySelector('form[action="/checkout"], form[action*="/checkout"]');
console.log('Checkout form:', !!checkoutForm);

// Check the checkout button
const checkoutBtn = document.querySelector('[name="checkout"], .cart__checkout-button');
console.log('Checkout button:', !!checkoutBtn, checkoutBtn?.disabled);

// Force redirect to checkout:
window.location.href = '/checkout';
```

## 12.2 Cart Page vs Cart Drawer
[TAGS: cart page, cart drawer, cart sidebar, slide cart, mini cart, ajax cart, cart popup]

Themes may use:
- **Cart page** (`/cart`) — traditional full-page cart
- **Cart drawer** — slide-out panel, updated via AJAX
- **Cart popup/notification** — small popup showing added item
- **Direct to checkout** — skip cart entirely

### Detecting cart type:
```javascript
const cartDrawer = document.querySelector('cart-drawer, .cart-drawer, #cart-drawer, [data-cart-drawer]');
const cartNotification = document.querySelector('cart-notification, .cart-notification');
console.log('Cart drawer:', !!cartDrawer);
console.log('Cart notification:', !!cartNotification);
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 13: PERFORMANCE & LOADING ISSUES
# ═══════════════════════════════════════════════════════════════════

## 13.1 Slow Page / Script Blocking
[TAGS: performance, slow, loading, render blocking, script blocking, heavy scripts, page speed, lazy load]

### Common causes of slow Shopify pages:
1. **Too many app scripts** — each app adds JS to every page via content_for_header
2. **Render-blocking CSS** — large CSS files in `<head>` without `media` attribute
3. **Synchronous scripts** — scripts without `defer` or `async`
4. **Large images** — not using srcset or lazy loading
5. **Excessive DOM size** — too many elements (> 1500)
6. **MutationObserver loops** — two scripts fighting each other
7. **Excessive console logging** — some apps spam console with data

### Quick performance check:
```javascript
(function() {
  console.log('[TS-PERF] Scripts:', document.querySelectorAll('script').length);
  console.log('[TS-PERF] Stylesheets:', document.querySelectorAll('link[rel="stylesheet"]').length);
  console.log('[TS-PERF] Style tags:', document.querySelectorAll('style').length);
  console.log('[TS-PERF] DOM elements:', document.querySelectorAll('*').length);
  console.log('[TS-PERF] Images:', document.querySelectorAll('img').length);
  console.log('[TS-PERF] Lazy images:', document.querySelectorAll('img[loading="lazy"]').length);
  
  // Check for render-blocking scripts
  const blockingScripts = document.querySelectorAll('head script:not([defer]):not([async])');
  console.log('[TS-PERF] Render-blocking scripts:', blockingScripts.length);
  blockingScripts.forEach(s => {
    if (s.src) console.log('[TS-PERF] Blocking:', s.src.split('/').pop());
  });
})();
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 14: MULTI-CURRENCY & LOCALIZATION
# ═══════════════════════════════════════════════════════════════════

## 14.1 Currency Issues
[TAGS: currency, multi-currency, price format, money format, exchange rate, localization, locale, language]

### Detecting currency settings:
```javascript
console.log('Active currency:', Shopify.currency?.active);
console.log('Rate:', Shopify.currency?.rate);
console.log('Locale:', Shopify.locale);
console.log('Country:', Shopify.country);
console.log('Routes root:', Shopify.routes?.root); // "/en/" for multi-language
```

### Common currency issues:
- Prices show in wrong currency → check currency selector, country detection
- Prices don't update when switching currency → Section Rendering API not triggered
- Some apps don't support multi-currency → they show base currency prices
- Currency formatting wrong → check Shopify.money_format or theme's format settings


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 15: SEARCH, COLLECTIONS & FILTERING
# ═══════════════════════════════════════════════════════════════════

## 15.1 Collection Filtering Issues
[TAGS: collection, filter, faceted, sort, pagination, filtering, facet, tag filter, collection page]

### Standard filtering mechanism (OS 2.0):
```
URL pattern: /collections/handle?filter.v.option.size=Small&filter.v.price.gte=10
Custom element: <facet-filters-form>
Event: Dispatches 'facet:update' and uses Section Rendering API
```

### Common issues:
- Filters don't work → JavaScript error in facet-filters-form.js
- Filter counts wrong → caching issue or app conflict
- Filters disappear → section not rendered or app hiding them
- Products don't update → Section Rendering API call fails

## 15.2 Search Issues
[TAGS: search, predictive search, search results, no results, search broken]

### Predictive search:
```
Custom element: <predictive-search>
API: GET /search/suggest.json?q=term&resources[type]=product,collection,article,page
```

### Search page:
```
Template: search.json
URL: /search?q=term&type=product
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 16: MOBILE-SPECIFIC ISSUES
# ═══════════════════════════════════════════════════════════════════

## 16.1 Mobile Layout Problems
[TAGS: mobile, responsive, viewport, touch, sticky, fixed, overflow, scroll, mobile layout]

### Common mobile-only issues:
1. **Horizontal scroll** — element wider than viewport
2. **Sticky header covering content** — z-index or position issue
3. **Touch targets too small** — buttons under 44x44px
4. **Fixed positioning conflicts** — multiple fixed elements stacking
5. **Overflow hidden on body** — modal/drawer didn't clean up
6. **Viewport meta tag missing or wrong** — `<meta name="viewport" content="width=device-width, initial-scale=1.0">`

### Quick mobile check:
```javascript
(function() {
  // Check for horizontal overflow
  if (document.body.scrollWidth > window.innerWidth)
    console.log('[TS-DIAG] HORIZONTAL OVERFLOW: body is', document.body.scrollWidth - window.innerWidth, 'px wider than viewport');
  
  // Check viewport meta
  const vpMeta = document.querySelector('meta[name="viewport"]');
  console.log('[TS-DIAG] Viewport meta:', vpMeta?.content || 'MISSING');
  
  // Check for stuck body overflow
  const bodyOverflow = getComputedStyle(document.body).overflow;
  if (bodyOverflow === 'hidden')
    console.log('[TS-DIAG] WARNING: body overflow is hidden (stuck modal/drawer?)');
})();
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 17: ERROR INTERPRETATION GUIDE
# ═══════════════════════════════════════════════════════════════════

## 17.1 Common Console Errors & What They Mean
[TAGS: error, console error, TypeError, ReferenceError, SyntaxError, interpretation, meaning, decode error]

```
"Cannot read properties of undefined (reading 'variants')"
→ Product JSON/object wasn't loaded or is null. Check if product data is available.

"Cannot read properties of null (reading 'addEventListener')"  
→ querySelector returned null. Element doesn't exist yet or selector is wrong.

"Failed to execute 'define' on 'CustomElementRegistry': the name '...' has already been used"
→ Custom element JS loaded twice. Check for duplicate script tags.

"Uncaught TypeError: X is not a function"
→ Something overwrote a function (monkey-patching gone wrong).

"net::ERR_NAME_NOT_RESOLVED"
→ DNS failure. The domain doesn't exist or is unreachable. Often = fake/removed app.

"net::ERR_BLOCKED_BY_CLIENT"
→ Ad blocker or browser extension blocking the request.

"Refused to execute script from '...' because 'script-src' CSP directive"
→ Content Security Policy blocking script execution. Extension uses debugger to bypass.

"422 Unprocessable Entity" on /cart/add.js
→ Invalid data sent. Usually: empty variant_id, unavailable variant, or invalid selling_plan.

"429 Too Many Requests"
→ Rate limited. Rarely seen on Ajax API but possible on Storefront API.

"Mixed Content: ... was loaded over HTTPS but requested an insecure resource"
→ HTTP resource on HTTPS page. Update URL to HTTPS.
```

## 17.2 Network Error Patterns
[TAGS: network error, 404, 500, 422, 403, network failure, request failed, status code]

```
404 on /cart/add.js     → URL is wrong (maybe missing locale prefix). Use Shopify.routes.root
404 on script URL       → App uninstalled but script tag remains
500 on any endpoint     → Shopify server error (temporary, retry)
422 on /cart/add.js     → Bad request data (variant_id empty, product unavailable)
403 on /cart/add.js     → Possible bot protection or app intercepting
301/302 on /cart/add    → Non-AJAX form post, Shopify redirecting to cart/checkout
```


---

# ═══════════════════════════════════════════════════════════════════
# SECTION 18: QUICK REFERENCE — COPY-PASTE FIXES
# ═══════════════════════════════════════════════════════════════════

## 18.1 Universal Sabotage Neutralizer
[TAGS: universal fix, nuclear option, comprehensive fix, fix everything, sabotage neutralizer, master fix]

When everything is broken and you need a shotgun approach:

```javascript
(function() {
  'use strict';
  
  // === PHASE 1: Kill switches ===
  window.__SABOTAGE_NEUTRALIZED__ = true;
  window.__CART_GUARD_DISABLED__ = true;
  window.__INTERCEPT_OFF__ = true;
  
  // === PHASE 2: Restore native functions ===
  const iframe = document.createElement('iframe');
  iframe.style.display = 'none';
  document.body.appendChild(iframe);
  try {
    window.fetch = iframe.contentWindow.fetch.bind(window);
    XMLHttpRequest.prototype.open = iframe.contentWindow.XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.send = iframe.contentWindow.XMLHttpRequest.prototype.send;
  } catch(e) {}
  document.body.removeChild(iframe);
  
  // === PHASE 3: Fix submit button ===
  document.querySelectorAll('button[name="add"], .product-form__submit, [data-add-to-cart], button[type="submit"]').forEach(btn => {
    btn.disabled = false;
    btn.removeAttribute('aria-disabled');
    btn.removeAttribute('style');
    btn.dataset.tsFixed = 'true';
    if (btn.textContent.includes('Unavailable')) {
      btn.textContent = 'Add to cart';
    }
  });
  
  // === PHASE 4: Fix variant inputs ===
  document.querySelectorAll('input[name="id"], select[name="id"]').forEach(input => {
    input.disabled = false;
    if (input.dataset.originalVariant) input.value = input.dataset.originalVariant;
    input.dataset.tsFixed = 'true';
  });
  
  // === PHASE 5: Fix quantity ===
  document.querySelectorAll('input[name="quantity"]').forEach(input => {
    input.readOnly = false;
    input.min = '1';
    input.max = '';
    if (input.value === '0') input.value = '1';
    if (input.dataset.originalValue) input.value = input.dataset.originalValue;
    input.style.cssText = '';
    input.dataset.tsFixed = 'true';
  });
  document.querySelectorAll('quantity-input button').forEach(btn => {
    btn.disabled = false;
    btn.style.opacity = '1';
    btn.style.pointerEvents = 'auto';
    btn.dataset.tsFixed = 'true';
  });
  
  // === PHASE 6: Restore option labels ===
  document.querySelectorAll('select[name="id"] option').forEach(opt => {
    if (opt.dataset.originalLabel) opt.textContent = opt.dataset.originalLabel;
  });
  
  // === PHASE 7: Remove sabotage elements ===
  document.querySelectorAll('[id*="sabotage"], [class*="sabotage"], .sabotage-overlay').forEach(el => el.remove());
  
  // === PHASE 8: Remove sabotage styles ===
  document.querySelectorAll('style').forEach(s => {
    const text = s.textContent;
    if (text.includes('z-index: -999') || text.includes('clip-path: inset') || 
        text.includes('-webkit-text-fill-color: transparent') || text.includes('sabotage')) {
      s.remove();
    }
  });
  
  // === PHASE 9: Inject comprehensive counter-CSS ===
  const fixCSS = document.createElement('style');
  fixCSS.id = 'ts-sidekick-master-fix';
  fixCSS.textContent = `
    product-form, .product-form { transform: none !important; opacity: 1 !important; pointer-events: auto !important; max-height: none !important; overflow: visible !important; }
    .product-form__submit, button[name="add"] { opacity: 1 !important; z-index: auto !important; clip-path: none !important; pointer-events: auto !important; cursor: pointer !important; position: relative !important; }
    .price-item, .price-item--regular, .price-item--sale, .price-item--last { color: inherit !important; -webkit-text-fill-color: inherit !important; font-size: inherit !important; letter-spacing: normal !important; opacity: 1 !important; visibility: visible !important; display: inline !important; overflow: visible !important; }
    .product__media-list, .product__media-item, .product-media-container, .product__media-wrapper { filter: none !important; opacity: 1 !important; }
    .product__info-wrapper, .product__info-container { position: static !important; top: auto !important; max-height: none !important; overflow: visible !important; }
    .product__description, .product-description, [class*="product-description"] { color: inherit !important; -webkit-text-fill-color: inherit !important; background: transparent !important; }
    .product__description::after, .product-description::after { content: none !important; display: none !important; }
    [data-widget-id], .bundler-target-product, .rebuy-widget, .vitals-widget { display: block !important; visibility: visible !important; opacity: 1 !important; max-height: none !important; overflow: visible !important; }
    .bis-button, [class*="notify"], .BIS_trigger { display: inline-block !important; visibility: visible !important; opacity: 1 !important; position: static !important; transform: none !important; pointer-events: auto !important; }
    .product-recommendations, [class*="related-product"] { opacity: 1 !important; filter: none !important; max-height: none !important; pointer-events: auto !important; }
    .product__tax, .product-form__quantity, quantity-input { transform: none !important; opacity: 1 !important; position: static !important; z-index: auto !important; }
    .breadcrumbs, .breadcrumb, a[href*="/collections/"] { font-size: inherit !important; line-height: inherit !important; opacity: 1 !important; max-height: none !important; overflow: visible !important; }
    .product-form__input .form__label, .variant__label { visibility: visible !important; height: auto !important; overflow: visible !important; }
  `;
  document.head.appendChild(fixCSS);
  
  // === PHASE 10: Protect with MutationObserver ===
  const protectedSelectors = 'button[name="add"], .product-form__submit, input[name="id"], select[name="id"], input[name="quantity"]';
  const protector = new MutationObserver(() => {
    document.querySelectorAll(protectedSelectors).forEach(el => {
      if (el.dataset.tsFixed && el.disabled) {
        el.disabled = false;
        el.removeAttribute('aria-disabled');
      }
    });
  });
  protector.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['disabled', 'aria-disabled', 'style'] });
  
  console.log('[TS-SIDEKICK] Universal Sabotage Neutralizer applied — 10 phases complete');
})();
```

This single script handles the most common 80% of sabotage scenarios. Use it when the page is heavily broken and you need a fast fix before doing targeted investigation.
