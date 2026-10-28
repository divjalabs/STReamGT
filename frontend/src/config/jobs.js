// Job statuses, in one place.
//
// These lists used to be copied into four files, which is how `rendering` came to be missing from
// the progress steps: the backend has it, the stepper didn't, and a job passing through it showed
// no progress at all.

/** The run's visible progress, in order. Mirrors JobStatus in backend/app/models/enums.py. */
export const JOB_STEPS = ["queued", "staging", "running", "uploading", "succeeded"];

/** A job in one of these states is finished; anything else is still in flight. */
export const TERMINAL_STATUSES = ["succeeded", "failed"];

export const isTerminal = (status) => TERMINAL_STATUSES.includes(status);

/**
 * Can the user stop this run? Everything unfinished except while results are being saved —
 * that phase writes results, ingests genotypes and locks the kit, so it is too late to cut short.
 */
export const isStoppable = (status) => !isTerminal(status) && status !== "uploading";
