class ProductManager {
    constructor() {
        this.products = [];
        this.init();
    }

    async init() {
        await this.loadProducts();
        this.renderProducts();
    }

    async loadProducts() {
        try {
            const response = await fetch('config/products.json');
            const data = await response.json();
            this.products = data.products;
        } catch (error) {
            console.error('Failed to load products:', error);
            this.products = [];
        }
    }

    renderProducts() {
        const container = document.getElementById('products-container');
        if (!container) return;

        const buttonsHtml = this.products.map(product => `
            <div class="product-item">
                <button class="btn" onclick="redirectToLicense('${product.id}')">
                    ${product.name}
                </button>
                <div class="price-box">
                    <img src="icon/Robux.svg" alt="Robux Icon" class="robux-icon">
                    <span class="price">${product.price}</span>
                </div>
                <p class="product-description">${product.description}</p>
            </div>
        `).join('');

        container.innerHTML = `
            <div class="products-grid">
                ${buttonsHtml}
            </div>
        `;
    }
}

function redirectToLicense(productId) {
    window.location.href = `license.html?product=${productId}`;
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    new ProductManager();
});
