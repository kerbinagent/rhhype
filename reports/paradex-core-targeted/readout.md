# Local bounded-read failure

The targeted metadata attempt stopped before WebSocket capture or paper orders. aiohttp StreamReader.read(n) returned an available partial chunk of the Core JSON response; the archived prefix failed JSON parsing. The local size guard incorrectly treated one read as complete. A new collector will accumulate bounded chunks through EOF. The failed source and partial response remain preserved, and all trading rules stay fixed.
