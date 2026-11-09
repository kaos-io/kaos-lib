// Recognising a KAOS pipeline repository.
// Why: the extension must stay inactive in every other folder. The check reads three markers only, through a small
// file-system interface, so it is tested without a disk.

export const COMPAT_FILE = ".kaos/compat.yaml";
export const DATASET_CONFIG_FILE = ".kubecore/dataset-config.yaml";
export const PIPELINE_FILE = "pipeline.py";

export interface FolderReader {
  exists(relativePath: string): Promise<boolean>;
  /** The first `maxBytes` of a text file, or undefined when it is missing. */
  readHead(relativePath: string, maxBytes: number): Promise<string | undefined>;
}

const HEAD_BYTES = 64 * 1024;

// `from kubecore.authoring import ...` or `import kubecore.authoring` or `from kubecore import authoring`.
const AUTHORING_IMPORT = /^[ \t]*(?:from[ \t]+kubecore\.authoring[ \t]+import\b|import[ \t]+kubecore\.authoring\b|from[ \t]+kubecore[ \t]+import[ \t]+(?:\([ \t]*)?[^\n#]*\bauthoring\b)/m;

/** True when the Python text imports the KAOS authoring module. Reads text only; nothing is run. */
export function importsAuthoring(pythonText: string): boolean {
  return AUTHORING_IMPORT.test(pythonText);
}

export type Marker = typeof COMPAT_FILE | typeof DATASET_CONFIG_FILE | "pipeline.py imports kubecore.authoring";

/** Which marker makes this folder a KAOS pipeline repository, or undefined when none does. */
export async function detectKaosRepo(folder: FolderReader): Promise<Marker | undefined> {
  if (await folder.exists(COMPAT_FILE)) { return COMPAT_FILE; }
  if (await folder.exists(DATASET_CONFIG_FILE)) { return DATASET_CONFIG_FILE; }
  const head = await folder.readHead(PIPELINE_FILE, HEAD_BYTES);
  if (head !== undefined && importsAuthoring(head)) { return "pipeline.py imports kubecore.authoring"; }
  return undefined;
}
