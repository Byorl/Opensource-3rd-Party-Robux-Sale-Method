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
            let response;
            try {
                response = await fetch('http://localhost:5000/products');
            } catch (serverError) {
                console.warn('Server not available, loading from local file');
                response = await fetch('config/products.json');
            }

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

        if (this.products.length === 0) {
            container.innerHTML = `
                <div class="loading-container">
                    <div class="loading"></div>
                    <p>Loading products...</p>
                </div>
            `;
            return;
        }

        const buttonsHtml = this.products.map(product => `
            <div class="product-item" data-product-id="${product.id}">
                <h3 class="product-name">${product.name}</h3>
                <div class="price-box">
                    <img src="icon/Robux.svg" alt="Robux Icon" class="robux-icon">
                    <span class="price">${product.price}</span>
                </div>
                <button class="btn" onclick="redirectToLicense('${product.id}')">
                    Purchase License
                </button>
            </div>
        `).join('');

        container.innerHTML = `
            <div class="products-grid">
                ${buttonsHtml}
            </div>
        `;

        this.addProductAnimations();
    }

    addProductAnimations() {
        const productItems = document.querySelectorAll('.product-item');
        productItems.forEach((item, index) => {
            item.style.opacity = '0';
            item.style.transform = 'translateY(20px)';

            setTimeout(() => {
                item.style.transition = 'all 0.5s ease';
                item.style.opacity = '1';
                item.style.transform = 'translateY(0)';
            }, index * 150);
        });
    }
}

function redirectToLicense(productId) {
    window.location.href = `license.html?product=${productId}`;
}

document.addEventListener('DOMContentLoaded', () => {
    new ProductManager();
});
