// Opens Razorpay's checkout for the order on this page. When Razorpay reports success, its
// payment id and signature are posted to EduNexa, which verifies them and asks Razorpay for the
// real amount before recording anything. The options come from a json_script block, so the
// Content-Security-Policy needs no inline script.
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector("[data-razorpay-open]");
    var data = document.getElementById("razorpay-options");
    var form = document.getElementById("razorpay-result");
    if (!button || !data || !form || typeof window.Razorpay !== "function") {
      return;
    }
    var options = JSON.parse(data.textContent);
    options.handler = function (result) {
      form.elements.razorpay_payment_id.value = result.razorpay_payment_id;
      form.elements.razorpay_signature.value = result.razorpay_signature;
      form.submit();
    };
    button.addEventListener("click", function () {
      new window.Razorpay(options).open();
    });
  });
})();
