// 1p external script creates an element and adds a listener
var fpDiv = document.createElement('div');
fpDiv.id = 'fp-div';
fpDiv.setAttribute('aria-label', '1p created div');
document.body.appendChild(fpDiv);

fpDiv.addEventListener('click', function() {});
