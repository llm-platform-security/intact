// end of 3p→3p chain — chain_b.js (loaded by chain_a.js) creates a span
var chainBSpan = document.createElement('span');
chainBSpan.id = 'chain-b-span';
document.body.appendChild(chainBSpan);

// 3p injects a textContent (inline) script that creates an element
// SYNCHRONOUSLY inside chain_b.js's appendChild call. The instrumentation tags
// the script element with a synthetic sourceURL at insertion time, so
// attribution survives even when V8 wouldn't have shown chain_b.js on the
// stack (e.g., async callbacks defined inside the inline body — see below).
var inlineScript = document.createElement('script');
inlineScript.textContent = [
  "var imgInline = document.createElement('img');",
  "imgInline.id = 'chain-b-inline-img';",
  "imgInline.setAttribute('aria-label', 'inline img from 3p-injected script');",
  "imgInline.src = 'https://thirdparty.test/pixel2.gif';",
  "document.body.appendChild(imgInline);"
].join('\n');
document.head.appendChild(inlineScript);

// 3p injects a textContent (inline) script that creates an element
// ASYNCHRONOUSLY (inside setTimeout). chain_b.js is NOT on the call stack when
// the async createElement fires, so a stack-trace-only approach would attribute
// the element to '1p:inline'. The synthetic sourceURL we set on the inline script
// at insertion time means V8 reports the setTimeout callback's source as
// cdpprov://dynamic-inline/<hash>, which callerUrl() resolves back to chain_b.js.
var asyncInlineScript = document.createElement('script');
asyncInlineScript.textContent = [
  "setTimeout(function() {",
  "  var asyncImg = document.createElement('img');",
  "  asyncImg.id = 'chain-b-async-inline-img';",
  "  asyncImg.setAttribute('aria-label', 'async inline img from 3p-injected script');",
  "  asyncImg.src = 'https://thirdparty.test/pixel3.gif';",
  "  document.body.appendChild(asyncImg);",
  "  window.__testComplete = true;",
  "}, 50);"
].join('\n');
document.head.appendChild(asyncInlineScript);
