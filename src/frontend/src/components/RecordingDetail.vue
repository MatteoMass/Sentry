<script setup lang="ts">
/**
 * The centre pane: everything the API knows about the selected recording.
 *
 * What the pipeline produces — transcript, summary — is not exposed over HTTP
 * yet, so the panel stops at the index for now.
 */
import { computed } from "vue";

import StatusBadge from "@/components/StatusBadge.vue";
import { useLibrary } from "@/composables/useLibrary";

const { selected, selectedPath } = useLibrary();

/** The folders leading to the recording, as one readable line. */
const location = computed(() =>
  selectedPath.value.length
    ? selectedPath.value.map((folder) => folder.name).join(" / ")
    : "Top level",
);

const uploadedAt = computed(() => {
  const raw = selected.value?.uploaded_at;
  if (raw === undefined) {
    return "";
  }
  const moment = new Date(raw);
  return Number.isNaN(moment.getTime())
    ? raw
    : moment.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
});
</script>

<template>
  <main class="detail">
    <div v-if="selected === null" class="placeholder">
      <p>No recording selected.</p>
      <p class="muted">Pick one on the left to see its details.</p>
    </div>

    <article v-else class="content">
      <header class="head">
        <p class="location muted">{{ location }}</p>
        <h2 class="name">{{ selected.name }}</h2>
        <StatusBadge :status="selected.status" />
      </header>

      <dl class="facts">
        <div class="fact">
          <dt>Uploaded</dt>
          <dd>{{ uploadedAt }}</dd>
        </div>
        <div class="fact">
          <dt>Identifier</dt>
          <dd class="mono">{{ selected.id }}</dd>
        </div>
        <div class="fact">
          <dt>Folder</dt>
          <dd class="mono">{{ selected.folder ?? "—" }}</dd>
        </div>
      </dl>

      <section class="pending">
        <h3>Processing output</h3>
        <p class="muted">
          Nothing to show yet: the pipeline results are not exposed by the API.
        </p>
      </section>
    </article>
  </main>
</template>

<style scoped>
.detail {
  flex: 1;
  height: 100%;
  overflow: auto;
  background: var(--surface-sunken);
}

.content {
  max-width: 780px;
  margin: 0 auto;
  padding: 2rem 2.5rem;
}

.head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
}

.location {
  margin: 0;
  font-size: 0.82rem;
  letter-spacing: 0.02em;
}

.name {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1.25rem;
  margin: 1.5rem 0 0;
}

.fact dt {
  margin-bottom: 0.2rem;
  color: var(--text-muted);
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.fact dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.88rem;
}

.pending {
  margin-top: 2.5rem;
  padding: 1.25rem;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.pending h3 {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
  font-weight: 600;
}

.pending p {
  margin: 0;
  font-size: 0.9rem;
}
</style>
