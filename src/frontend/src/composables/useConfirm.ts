/**
 * The question asked before something is destroyed.
 *
 * One question stands at a time and the caller waits for the answer, so a
 * delete reads as a single step: ask, then act on what came back.
 */

import { readonly, ref } from "vue";

/** What the dialog puts on screen. */
export interface Question {
  title: string;
  /** What is at stake, when the title does not say it all. */
  body?: string;
  /** Label of the button that goes through with it. */
  confirm: string;
  /** True when going through with it destroys something. */
  danger?: boolean;
}

const question = ref<Question | null>(null);

/** How the promise handed to the caller is settled. */
let pending: ((answer: boolean) => void) | null = null;

/** Ask, and answer with what was chosen. */
function ask(asked: Question): Promise<boolean> {
  // A second question while one stands would leave the first unanswered.
  answer(false);
  question.value = asked;
  return new Promise<boolean>((settle) => {
    pending = settle;
  });
}

/** Close the dialog, answering whoever is waiting on it. */
function answer(chosen: boolean): void {
  const settle = pending;
  pending = null;
  question.value = null;
  settle?.(chosen);
}

export function useConfirm() {
  return { question: readonly(question), ask, answer };
}
