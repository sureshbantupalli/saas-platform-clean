document.addEventListener("DOMContentLoaded", function () {

    const tenantField = document.getElementById("id_tenant");

    if (tenantField) {
        tenantField.addEventListener("change", function () {

            const tenantId = this.value;

            if (tenantId) {
                const url = new URL(window.location.href);
                url.searchParams.set("tenant", tenantId);
                window.location.href = url.toString();
            }

        });
    }

});