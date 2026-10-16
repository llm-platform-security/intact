// 3p external script (served from thirdparty.test)
// Creates elements via createElement and innerHTML
var tpBtn = document.createElement('button');
tpBtn.id = 'tp-btn';
tpBtn.setAttribute('role', 'button');
document.body.appendChild(tpBtn);

var tpContainer = document.createElement('div');
tpContainer.id = 'tp-container';
document.body.appendChild(tpContainer);
tpContainer.innerHTML = '<span id="tp-inner-span">3p innerHTML content</span>';
