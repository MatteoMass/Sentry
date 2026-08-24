<script setup lang="ts">
/** Where a recording sits in the pipeline, said in one word and one colour. */
import { computed } from "vue";

import type { RecordingStatus } from "@/api/types";

const props = defineProps<{ status: RecordingStatus }>();

const LABELS: Record<RecordingStatus, string> = {
  to_process: "To process",
  transcribing: "Transcribing",
  transcribed: "Transcribed",
  summarizing: "Summarising",
  processed: "Processed",
  error: "Error",
};

const label = computed(() => LABELS[props.status] ?? props.status);
</script>

<template>
  <span class="badge" :class="`badge--${props.status}`">
    <span class="dot" />
    {{ label }}
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4em;
  padding: 0.15em 0.6em;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 500;
  white-space: nowrap;
}

.dot {
  width: 0.5em;
  height: 0.5em;
  border-radius: 50%;
  background: currentColor;
}

.badge--to_process {
  color: var(--status-to-process);
}
.badge--transcribing,
.badge--summarizing {
  color: var(--status-running);
}
.badge--transcribed {
  color: var(--status-transcribed);
}
.badge--processed {
  color: var(--status-processed);
}
.badge--error {
  color: var(--status-error);
}
</style>
