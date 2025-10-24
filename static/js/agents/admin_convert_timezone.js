document.addEventListener("DOMContentLoaded", function() {
    const elements = document.querySelectorAll(".utc-date");
    elements.forEach(el => {
        const utcStr = el.getAttribute("data-utc");
        if (utcStr) {
            const dt = new Date(utcStr);
            const options = { year:"numeric", month:"short", day:"numeric", hour:"numeric", minute:"numeric", hour12:true };
            el.textContent = dt.toLocaleString(undefined, options);
        }
    });
});