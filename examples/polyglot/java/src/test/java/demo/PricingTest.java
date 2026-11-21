package demo;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.assertEquals;
public class PricingTest {
    @ParameterizedTest @ValueSource(ints = {1, 2})
    void total(int quantity) { assertEquals(quantity * 100, Pricing.total(quantity)); }
}
