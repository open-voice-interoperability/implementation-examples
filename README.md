# implementation-examples
Examples of implementations of OVON interoperability specifications.

## OpenFloor installation note
`openfloor` is published on TestPyPI (not PyPI).

If you need to run code that imports `openfloor`, install it with:

```bash
pip install events==0.5
pip install --index-url https://test.pypi.org/simple/ --no-deps openfloor==0.1.4
```

See [assistantClient setup](./assistantClient/README.md#installation) for full local setup steps.

## Agents and Templates
- [erin](./erin/README.md) - Hallucination demo agent that intentionally includes at least one incorrect claim.
- [stella](./stella/README.md) - Space and astronomy assistant backed by NASA APIs.
- [verity](./verity/) - Fact-checking agent that detects and mitigates hallucinations.
- [time-agent](./time-agent/README.md) - World time agent for major cities.
- [agent-template](./agent-template/README.md) - OpenFloor agent template with full event handling.

## Earlier Specification Samples
These folders are based on earlier versions of the specifications and are kept for reference:
- [aws-interop-sample](./aws-interop-sample/README.md)
- [go-examples](./go-examples/)
- [js-examples](./js-examples/README.md)
- [mcp](./mcp/)
- [websockets](./websockets/README.md)
