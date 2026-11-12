// esbuild incrusta el .wasm en el bundle como bytes (--loader:.wasm=binary).
declare module "*.wasm" {
  const bytes: Uint8Array;
  export default bytes;
}
