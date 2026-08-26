<script setup lang="ts">
/**
 * An answer, drawn as the Markdown it was written in.
 *
 * Every run of text lands in a real element and nothing is ever handed to
 * `v-html`: the text comes from a model reading somebody's recording, and
 * that is not a place page markup may come from. What the parser could not
 * read stays on screen as the characters it was written as.
 */
import { computed } from "vue";

import { blocks } from "@/components/markdown";

const props = defineProps<{ text: string }>();

const parsed = computed(() => blocks(props.text));
</script>

<template>
  <div class="markdown">
    <template v-for="(block, index) in parsed" :key="index">
      <pre v-if="block.kind === 'code'" class="md-code"><code>{{ block.text }}</code></pre>

      <hr v-else-if="block.kind === 'rule'" class="md-rule" />

      <component
        :is="block.ordered ? 'ol' : 'ul'"
        v-else-if="block.kind === 'list'"
        class="md-list"
      >
        <li v-for="(item, entry) in block.items" :key="entry">
          <template v-for="(piece, run) in item" :key="run">
            <a
              v-if="piece.kind === 'link'"
              :href="piece.href"
              target="_blank"
              rel="noopener noreferrer"
              >{{ piece.text }}</a
            >
            <strong v-else-if="piece.kind === 'strong'">{{ piece.text }}</strong>
            <em v-else-if="piece.kind === 'emphasis'">{{ piece.text }}</em>
            <code v-else-if="piece.kind === 'code'" class="md-tick">{{ piece.text }}</code>
            <template v-else>{{ piece.text }}</template>
          </template>
        </li>
      </component>

      <component :is="block.tag" v-else class="md-block">
        <template v-for="(piece, run) in block.pieces" :key="run">
          <a
            v-if="piece.kind === 'link'"
            :href="piece.href"
            target="_blank"
            rel="noopener noreferrer"
            >{{ piece.text }}</a
          >
          <strong v-else-if="piece.kind === 'strong'">{{ piece.text }}</strong>
          <em v-else-if="piece.kind === 'emphasis'">{{ piece.text }}</em>
          <code v-else-if="piece.kind === 'code'" class="md-tick">{{ piece.text }}</code>
          <template v-else>{{ piece.text }}</template>
        </template>
      </component>
    </template>
  </div>
</template>

<style scoped>
/* The blocks sit closer together than prose would: an answer is read in a
   panel beside the recording, not on a page of its own. */
.markdown {
  font-size: 0.9rem;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.markdown > * + * {
  margin-top: 0.5rem;
}

.md-block {
  margin: 0;
}

/* A heading inside an answer names a part of it; the panel around it already
   carries the headings that matter, so none of these may outshout one. */
h1.md-block,
h2.md-block,
h3.md-block,
h4.md-block {
  font-size: 0.82rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--text-muted);
}

blockquote.md-block {
  padding-left: 0.7rem;
  border-left: 2px solid var(--border);
  color: var(--text-muted);
}

.md-list {
  margin: 0;
  padding-left: 1.15rem;
}

.md-list li + li {
  margin-top: 0.2rem;
}

.md-code {
  margin: 0;
  padding: 0.5rem 0.6rem;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.5;
}

.md-tick {
  padding: 0.05em 0.3em;
  border-radius: 3px;
  background: var(--surface-sunken);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82em;
}

.md-rule {
  height: 0;
  margin: 0.75rem 0;
  border: none;
  border-top: 1px solid var(--border);
}

.markdown a {
  color: var(--accent);
}
</style>
