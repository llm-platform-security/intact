// 3p script (loaded dynamically by inline code) creates a div
var chainADiv = document.createElement('div');
chainADiv.id = 'chain-a-div';
chainADiv.setAttribute('aria-label', 'created by chain_a');
document.body.appendChild(chainADiv);

// 3p script creates img with 3p src → triggers a 3p network request
var chainAImg = document.createElement('img');
chainAImg.id = 'chain-a-img';
chainAImg.src = 'https://thirdparty.test/pixel_a.gif';
document.body.appendChild(chainAImg);

// 3p→3p script injection — chain_a.js loads chain_b.js
var chainBTag = document.createElement('script');
chainBTag.id = 'chain-b-script-tag';
chainBTag.src = 'https://thirdparty.test/chain_b.js';
document.head.appendChild(chainBTag);
